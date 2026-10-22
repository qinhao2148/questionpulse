import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from fastapi import HTTPException


def issue_access_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def issue_join_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def pseudonymize_external_viewer(viewer_key: str, secret_key: str) -> str:
    digest = hmac.new(
        secret_key.encode("utf-8"), viewer_key.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"polyv_{digest}"


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
    # Sessions created before the role-boundary migration remain readable so
    # existing demo evidence is preserved. Every newly created session has a digest.
    if expected_digest is None:
        return
    if expires_at is not None:
        comparable_expiry = (
            expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at
        )
        if comparable_expiry <= datetime.now(UTC):
            raise HTTPException(status_code=403, detail="access_expired")
    supplied = bearer_token(authorization)
    if supplied is None or not hmac.compare_digest(expected_digest, token_digest(supplied)):
        raise HTTPException(status_code=403, detail="access_denied")
