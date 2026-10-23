import hashlib
import hmac
import secrets
from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException


def issue_access_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def issue_join_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def teacher_portal_token(
    username: str, secret_key: str, issued_at: datetime | None = None
) -> str:
    """Issue a teacher portal token as ``qpa_<issued_at>_<digest>``.

    The signature covers the username and the issue time so the token cannot
    be replayed forever or re-signed without the portal secret.
    """
    stamp = int((issued_at or datetime.now(UTC)).timestamp())
    digest = hmac.new(
        secret_key.encode("utf-8"), f"{username}:{stamp}".encode(), hashlib.sha256
    ).hexdigest()
    return f"qpa_{stamp}_{digest}"


def verify_teacher_portal_token(
    token: str | None,
    username: str,
    secret_key: str,
    ttl_hours: int,
) -> bool:
    """Check signature and age of a teacher portal token."""
    if not token:
        return False
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != "qpa":
        return False
    _, stamp_text, supplied_digest = parts
    if not stamp_text.isdigit():
        return False
    issued_at = datetime.fromtimestamp(int(stamp_text), UTC)
    now = datetime.now(UTC)
    if issued_at - now > timedelta(minutes=5):
        return False
    if now - issued_at > timedelta(hours=ttl_hours):
        return False
    expected_digest = hmac.new(
        secret_key.encode("utf-8"),
        f"{username}:{int(stamp_text)}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_digest, supplied_digest)


def pseudonymize_external_viewer(viewer_key: str, secret_key: str) -> str:
    digest = hmac.new(
        secret_key.encode("utf-8"), viewer_key.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    # POLYV viewer ids are limited to 64 ASCII characters. Keeping the value
    # within the documented limit also ensures chat-history ids can be mapped
    # back to the same QuestionPulse participant without server-side truncation.
    return f"qp_{digest[:61]}"


def issue_polyv_identity_auth(
    external_viewer_id: str,
    nickname: str,
    app_secret: str,
    timestamp_ms: int | None = None,
) -> dict[str, str | int]:
    """Issue POLYV viewer-user-system direct-auth parameters.

    The app secret never leaves the backend. A fresh millisecond timestamp is
    used for every classroom join because POLYV authorization signatures are
    short-lived and must not be reused as permanent student links.
    """
    timestamp = (
        timestamp_ms if timestamp_ms is not None else int(datetime.now(UTC).timestamp() * 1000)
    )
    sign_text = f"{app_secret}{external_viewer_id}{app_secret}{timestamp}"
    sign = hashlib.md5(sign_text.encode("utf-8")).hexdigest()  # noqa: S324
    encoded_nickname = urlsafe_b64encode(nickname.encode("utf-8")).decode("ascii").rstrip("=")
    return {
        "external_viewer_id": external_viewer_id,
        "nickname": encoded_nickname,
        "ts": timestamp,
        "sign": sign,
    }


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def verify_access_token(
    expected_digest: str | None,
    authorization: str | None,
    expires_at: datetime | None = None,
) -> None:
    """Verify a role-bound access token against its stored digest.

    A missing digest means the record predates role binding. That is an
    absence of evidence about the caller, never evidence of trust, so such
    records are denied instead of being waved through.
    """
    if expected_digest is None:
        raise HTTPException(status_code=403, detail="access_denied")
    if expires_at is not None:
        comparable_expiry = (
            expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at
        )
        if comparable_expiry <= datetime.now(UTC):
            raise HTTPException(status_code=403, detail="access_expired")
    supplied = bearer_token(authorization)
    if supplied is None or not hmac.compare_digest(expected_digest, token_digest(supplied)):
        raise HTTPException(status_code=403, detail="access_denied")
