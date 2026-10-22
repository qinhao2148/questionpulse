import hashlib
import hmac
import secrets

from fastapi import HTTPException


def issue_access_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def issue_join_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def verify_access_token(expected_digest: str | None, authorization: str | None) -> None:
    # Sessions created before the role-boundary migration remain readable so
    # existing demo evidence is preserved. Every newly created session has a digest.
    if expected_digest is None:
        return
    supplied = bearer_token(authorization)
    if supplied is None or not hmac.compare_digest(expected_digest, token_digest(supplied)):
        raise HTTPException(status_code=403, detail="access_denied")
