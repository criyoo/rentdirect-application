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

from .models import AppUser, Listing, Message
from .security import contains_contact_info
from .subscription_access import user_has_bronze_access, user_has_silver_access

try:
    import redis.asyncio as redis_async
except ImportError:  # pragma: no cover
    redis_async = None


DIRECT_MESSAGE_CHAT_PATH = "/ws/messages"
DIRECT_MESSAGE_CHANNEL_PREFIX = "rentdirect.messages"


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

    return (
        get_user_model()
        .objects
        .filter(id=user_id, is_active=True, role__in=[AppUser.Role.TENANT, AppUser.Role.LANDLORD])
        .first()
    )


def _message_payload(message):
    return {
        "id": str(message.id),
        "sender_id": str(message.sender_id),
        "receiver_id": str(message.receiver_id),
        "listing_id": str(message.listing_id) if message.listing_id else None,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
    }


@sync_to_async
def _resolve_conversation(user, scope):
    query = parse_qs(scope.get("query_string", b"").decode("utf-8"))
    listing_id = (query.get("listing_id") or [""])[0]
    counterpart_id = (query.get("counterpart_id") or [""])[0]
    if not listing_id:
        return None

    if user.role == AppUser.Role.TENANT and not user_has_silver_access(user):
        return None

    listing = Listing.objects.select_related("landlord").filter(id=listing_id).first()
    if listing is None:
        return None

    if user.role == AppUser.Role.TENANT:
        counterpart = listing.landlord
        if counterpart_id and str(counterpart.id) != counterpart_id:
            return None
    elif user.role == AppUser.Role.LANDLORD:
        if listing.landlord_id != user.id or not counterpart_id:
            return None
        counterpart = (
            get_user_model()
            .objects
            .filter(id=counterpart_id, role=AppUser.Role.TENANT, is_active=True)
            .first()
        )
        if counterpart is None:
            return None
    else:
        return None

    tenant_id = user.id if user.role == AppUser.Role.TENANT else counterpart.id
    return listing, counterpart, f"{DIRECT_MESSAGE_CHANNEL_PREFIX}.{listing.id}.{tenant_id}"


@sync_to_async
def _can_send_message(sender, receiver, content):
    if sender.role == AppUser.Role.TENANT and not sender.is_verified:
        return False, "Your account must be verified before contacting landlords. Please submit your NIN for verification."
    if sender.role == AppUser.Role.TENANT and receiver.role == AppUser.Role.LANDLORD:
        if not user_has_silver_access(sender):
            return False, "Contacting landlords is available from the Silver plan."
        if user_has_bronze_access(receiver):
            return False, "Landlord is unable to receive messages at this time until fully verified."
    if sender.role == AppUser.Role.LANDLORD and receiver.role == AppUser.Role.TENANT and user_has_bronze_access(sender):
        return False, "Contacting tenants is not available on the Bronze free plan."
    if contains_contact_info(content):
        return False, "Phone numbers, emails, and social media handles are not allowed. Please use chat only."
    return True, ""


@sync_to_async
def _create_message(sender, receiver, listing, content):
    message = Message.objects.create(
        sender=sender,
        receiver=receiver,
        listing=listing,
        content=content,
    )
    return _message_payload(message)


class DirectMessageChatHub:
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

        conversation = await _resolve_conversation(user, scope)
        if conversation is None:
            await receive()
            await send({"type": "websocket.close", "code": 4403})
            return

        connect_event = await receive()
        if connect_event.get("type") != "websocket.connect":
            return

        listing, counterpart, channel_name = conversation
        await send({"type": "websocket.accept"})
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
                if len(content) > 1000:
                    content = content[:1000]

                can_send, error = await _can_send_message(user, counterpart, content)
                if not can_send:
                    await send({"type": "websocket.send", "text": json.dumps({"type": "error", "detail": error})})
                    continue

                message_payload = await _create_message(user, counterpart, listing, content)
                await self.publish(channel_name, {"type": "message", **message_payload})

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


direct_message_chat_hub = DirectMessageChatHub()
