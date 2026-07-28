import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

django_application = get_asgi_application()

from core.community_chat import COMMUNITY_CHAT_PATH, community_chat_hub  # noqa: E402
from core.direct_message_chat import DIRECT_MESSAGE_CHAT_PATH, direct_message_chat_hub  # noqa: E402
from core.support_chat import SUPPORT_CHAT_PATH, support_chat_hub  # noqa: E402


async def application(scope, receive, send):
    path = scope.get("path", "").rstrip("/")
    if scope.get("type") == "websocket" and path == COMMUNITY_CHAT_PATH:
        await community_chat_hub(scope, receive, send)
        return
    if scope.get("type") == "websocket" and path == DIRECT_MESSAGE_CHAT_PATH:
        await direct_message_chat_hub(scope, receive, send)
        return
    if scope.get("type") == "websocket" and path == SUPPORT_CHAT_PATH:
        await support_chat_hub(scope, receive, send)
        return

    await django_application(scope, receive, send)
