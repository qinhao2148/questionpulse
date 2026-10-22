from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.auth import token_digest, verify_access_token
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
