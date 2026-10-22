import pytest

from app.api.routes import classroom
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def disable_real_llm_calls(monkeypatch):
    """Automated tests must never consume a developer's configured API key."""
    safe_settings = get_settings().model_copy(update={"llm_api_key": ""})
    monkeypatch.setattr(classroom, "get_settings", lambda: safe_settings)
