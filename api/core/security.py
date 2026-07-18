import hashlib
import hmac
import re
import secrets
import string

from django.conf import settings


OTP_LENGTH = 6
OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_ALPHABET = string.ascii_uppercase + string.digits

CONTACT_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "oh", "nil",
}


def generate_otp() -> str:
    return "".join(secrets.choice(OTP_ALPHABET) for _ in range(OTP_LENGTH))


def hash_otp(email: str, code: str) -> str:
    payload = f"{email.strip().lower()}:{code.strip().upper()}:{settings.SECRET_KEY}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def otp_matches(expected_hash: str, email: str, code: str) -> bool:
    return hmac.compare_digest(expected_hash or "", hash_otp(email, code))


def contains_contact_info(text: str) -> bool:
    value = (text or "").lower()
    if re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", value):
        return True
    if re.search(r"(@[a-z0-9_.]{2,})", value):
        return True
    if re.search(r"(wa\.me/|t\.me/|telegram|whatsapp|instagram|ig\b|facebook|fb\b|snapchat|tiktok|twitter|x\.com|linkedin)", value):
        return True
    match = re.search(r"(\+?\d[\d\s().-]{6,}\d)", value)
    if match and len(re.sub(r"\D", "", match.group(1))) >= 8:
        return True
    run = 0
    for token in re.findall(r"[a-z]+", value):
        run = run + 1 if token in CONTACT_WORDS else 0
        if run >= 8:
            return True
    return False
