from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api.routes.shared import require_teacher, require_teacher_portal
from app.core.auth import (
    pseudonymize_external_viewer,
    teacher_portal_token,
    token_digest,
    verify_access_token,
    verify_teacher_portal_token,
)
from app.core.config import Settings


def test_blank_llm_environment_values_use_safe_defaults() -> None:
    settings = Settings(llm_base_url="", llm_model="")
    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-flash"


def test_expired_access_token_is_rejected() -> None:
    token = "qpt_test-token"
    with pytest.raises(HTTPException) as error:
        verify_access_token(
            token_digest(token),
            f"Bearer {token}",
            datetime.now(UTC) - timedelta(seconds=1),
        )
    assert error.value.status_code == 403
    assert error.value.detail == "access_expired"


def test_record_without_token_digest_is_rejected() -> None:
    with pytest.raises(HTTPException) as error:
        verify_access_token(None, "Bearer qpt_anything")
    assert error.value.status_code == 403
    assert error.value.detail == "access_denied"


def test_missing_authorization_header_is_rejected() -> None:
    token = "qpt_test-token"
    with pytest.raises(HTTPException) as error:
        verify_access_token(token_digest(token), None)
    assert error.value.status_code == 403
    assert error.value.detail == "access_denied"


def test_teacher_portal_token_is_accepted_while_fresh() -> None:
    token = teacher_portal_token("0", "portal-secret")
    assert verify_teacher_portal_token(token, "0", "portal-secret", 24)


def test_teacher_portal_token_expires_after_ttl() -> None:
    issued_at = datetime.now(UTC) - timedelta(hours=25)
    token = teacher_portal_token("0", "portal-secret", issued_at)
    assert not verify_teacher_portal_token(token, "0", "portal-secret", 24)


def test_teacher_portal_token_rejects_wrong_secret_and_username() -> None:
    token = teacher_portal_token("0", "portal-secret")
    assert not verify_teacher_portal_token(token, "0", "other-secret", 24)
    assert not verify_teacher_portal_token(token, "1", "portal-secret", 24)


def test_legacy_static_teacher_token_is_rejected() -> None:
    assert not verify_teacher_portal_token("qpa_deadbeef", "0", "portal-secret", 24)
    assert not verify_teacher_portal_token(None, "0", "portal-secret", 24)


def test_production_refuses_shipped_default_credentials() -> None:
    with pytest.raises(ValueError, match="TEACHER_PASSWORD"):
        Settings(app_env="production", teacher_password="123456")


def test_development_keeps_default_credentials_usable() -> None:
    settings = Settings(app_env="development", teacher_password="123456")
    assert settings.teacher_password == "123456"


def test_external_viewer_pseudonym_is_keyed_and_stable() -> None:
    first = pseudonymize_external_viewer("viewer-123", "private-key-a")
    assert first == pseudonymize_external_viewer("viewer-123", "private-key-a")
    assert first != pseudonymize_external_viewer("viewer-123", "private-key-b")
    assert "viewer-123" not in first
    assert first.startswith("polyv_")


class _ClassroomStub:
    """Only the two fields require_teacher looks at."""

    teacher_token_hash = token_digest("qpt_valid-classroom-token")
    teacher_token_expires_at = None


def test_portal_endpoint_asks_for_login_when_token_is_stale() -> None:
    # The console and the browser extension need to tell "sign in again" apart
    # from "you may not do this", otherwise retrying looks like the only option.
    with pytest.raises(HTTPException) as error:
        require_teacher_portal("Bearer qpa_1_stale-digest")
    assert error.value.status_code == 403
    assert error.value.detail == "teacher_login_required"


def test_stale_portal_token_reports_login_not_permission_denied() -> None:
    with pytest.raises(HTTPException) as error:
        require_teacher(_ClassroomStub(), "Bearer qpa_1_stale-digest")
    assert error.value.status_code == 403
    assert error.value.detail == "teacher_login_required"


def test_wrong_classroom_token_keeps_permission_denied() -> None:
    with pytest.raises(HTTPException) as error:
        require_teacher(_ClassroomStub(), "Bearer qpt_wrong-token")
    assert error.value.status_code == 403
    assert error.value.detail == "access_denied"
