from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework.exceptions import APIException


class VerificationProviderUnavailable(APIException):
    status_code = 503
    default_detail = "Verification provider is not configured."
    default_code = "verification_provider_unavailable"


def _provider_module():
    provider = str(getattr(settings, "VERIFICATION_SERVICE", "dikript") or "dikript").strip().lower()
    if provider == "prembly":
        from . import prembly_verification as service

        return service
    if provider == "dikript":
        from . import dikript_verification as service

        return service
    raise VerificationProviderUnavailable(detail=f"Unsupported verification provider: {provider}")


def verify_nin_and_bvn(input_data: dict[str, Any], nin_number: str, bvn_number: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return _provider_module().verify_nin_and_bvn(input_data, nin_number, bvn_number)


def verify_cac(input_data: dict[str, Any], registration_number: str) -> dict[str, Any]:
    return _provider_module().verify_cac(input_data, registration_number)
