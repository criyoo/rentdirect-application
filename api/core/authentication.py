from rest_framework_simplejwt.authentication import JWTAuthentication

from django.conf import settings

from .roles import ACTIVE_ROLE_HEADER, apply_active_role


class CookieJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            authenticated = super().authenticate(request)
            if authenticated is None:
                return None
            user, validated_token = authenticated
            apply_active_role(user, request.META.get(ACTIVE_ROLE_HEADER))
            return user, validated_token

        raw_token = request.COOKIES.get(settings.ACCESS_COOKIE_NAME)
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)
        apply_active_role(user, request.META.get(ACTIVE_ROLE_HEADER))
        return user, validated_token
