import asyncio
import json
import os
import ssl
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from .models import AppUser, SupportChatMessage

try:
    import redis.asyncio as redis_async
except ImportError:  # pragma: no cover
    redis_async = None


SUPPORT_CHAT_PATH = "/ws/support-chat"
SUPPORT_CHAT_CHANNEL_PREFIX = "rentdirect.support-chat"


def _headers_dict(scope):
    return {key.lower(): value for key, value in scope.get("headers", [])}


def _access_token_from_scope(scope):
    cookie_header = _headers_dict(scope).get(b"cookie", b"").decode("latin1")
    cookies = SimpleCookie()
    cookies.load(cookie_header)
    morsel = cookies.get(settings.ACCESS_COOKIE_NAME)
    return morsel.value if morsel else ""


@sync_to_async
def _authenticate_user(scope):
    raw_token = _access_token_from_scope(scope)
    if not raw_token:
        return None

    try:
        token = AccessToken(raw_token)
    except TokenError:
        return None

    user_id = token.get("user_id")
    if not user_id:
        return None

    return get_user_model().objects.filter(id=user_id, is_active=True).first()


@sync_to_async
def _resolve_thread_user(user, scope):
    if user.role in {AppUser.Role.TENANT, AppUser.Role.LANDLORD}:
        return user
    if user.role != AppUser.Role.ADMIN:
        return None

    query = parse_qs(scope.get("query_string", b"").decode("utf-8"))
    thread_user_id = (query.get("user_id") or query.get("tenant_id") or query.get("landlord_id") or [""])[0]
    if not thread_user_id:
        return None

    return (
        get_user_model()
        .objects
        .filter(id=thread_user_id, role__in=[AppUser.Role.TENANT, AppUser.Role.LANDLORD], is_active=True)
        .first()
    )


def _message_payload(message):
    sender = message.sender
    return {
        "id": str(message.id),
        "thread_user_id": str(message.thread_user_id),
        "sender_id": str(sender.id),
        "sender_name": sender.name,
        "sender_role": sender.role,
        "sender_photo_url": sender.profile_photo_url,
        "is_support_message": message.sender_id != message.thread_user_id,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
    }


@sync_to_async
def _create_message(thread_user, sender, content):
    message = SupportChatMessage.objects.select_related("thread_user", "sender").create(
        thread_user=thread_user,
        sender=sender,
        content=content,
    )
    return _message_payload(message)


class SupportChatHub:
    def __init__(self):
        self.local_queues_by_channel = {}

    def redis_url(self):
        return os.environ.get("VALKEY_URL", os.environ.get("REDIS_URL", "")).strip()

    def redis_client(self):
        if redis_async is None:
            return None
        url = self.redis_url()
        if not url:
            return None
        kwargs = {}
        auth_token = os.environ.get("VALKEY_AUTH_TOKEN", "")
        if auth_token:
            kwargs["password"] = auth_token
        if url.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = ssl.CERT_NONE
        return redis_async.from_url(url, decode_responses=True, **kwargs)

    def channel_name(self, thread_user_id):
        return f"{SUPPORT_CHAT_CHANNEL_PREFIX}.{thread_user_id}"

    async def publish(self, channel_name, payload):
        encoded = json.dumps(payload)
        client = self.redis_client()
        if client is None:
            await self.broadcast_local(channel_name, encoded)
            return

        try:
            await client.publish(channel_name, encoded)
        except Exception:
            await self.broadcast_local(channel_name, encoded)
        finally:
            await client.aclose()

    async def broadcast_local(self, channel_name, encoded_payload):
        queues = self.local_queues_by_channel.get(channel_name, set())
        stale_queues = []
        for queue in queues:
            try:
                queue.put_nowait(encoded_payload)
            except asyncio.QueueFull:
                stale_queues.append(queue)
        for queue in stale_queues:
            queues.discard(queue)

    async def redis_subscribe(self, channel_name, queue):
        client = self.redis_client()
        if client is None:
            while True:
                await asyncio.sleep(3600)

        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(channel_name)
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    await queue.put(message.get("data", ""))
        except Exception:
            while True:
                await asyncio.sleep(3600)
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.aclose()
            await client.aclose()

    async def __call__(self, scope, receive, send):
        user = await _authenticate_user(scope)
        if user is None:
            await receive()
            await send({"type": "websocket.close", "code": 4401})
            return

        thread_user = await _resolve_thread_user(user, scope)
        if thread_user is None:
            await receive()
            await send({"type": "websocket.close", "code": 4403})
            return

        connect_event = await receive()
        if connect_event.get("type") != "websocket.connect":
            return

        await send({"type": "websocket.accept"})
        channel_name = self.channel_name(thread_user.id)
        queue = asyncio.Queue(maxsize=100)
        self.local_queues_by_channel.setdefault(channel_name, set()).add(queue)

        async def receive_loop():
            while True:
                event = await receive()
                event_type = event.get("type")
                if event_type == "websocket.disconnect":
                    break
                if event_type != "websocket.receive":
                    continue

                raw_text = event.get("text") or ""
                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError:
                    continue

                content = str(payload.get("content") or "").strip()
                if not content:
                    continue
                if len(content) > 2000:
                    content = content[:2000]

                message_payload = await _create_message(thread_user, user, content)
                await self.publish(channel_name, message_payload)

        async def send_loop():
            while True:
                encoded_payload = await queue.get()
                if encoded_payload:
                    await send({"type": "websocket.send", "text": encoded_payload})

        subscriber_task = asyncio.create_task(self.redis_subscribe(channel_name, queue))
        sender_task = asyncio.create_task(send_loop())
        receiver_task = asyncio.create_task(receive_loop())
        done, pending = await asyncio.wait(
            {subscriber_task, sender_task, receiver_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            if task.exception():
                break
        self.local_queues_by_channel.get(channel_name, set()).discard(queue)


support_chat_hub = SupportChatHub()
