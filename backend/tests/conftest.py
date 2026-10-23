import pytest

from app.api.routes import chat, checks, clusters, questions, reports, sessions, shared
from app.core.config import get_settings

MODULES = (shared, sessions, questions, clusters, reports, checks, chat)


@pytest.fixture(autouse=True)
def disable_real_llm_calls(monkeypatch):
    """Automated tests must never consume a developer's configured API key."""
    safe_settings = get_settings().model_copy(update={"llm_api_key": ""})
    for module in MODULES:
        if hasattr(module, "get_settings"):
            monkeypatch.setattr(module, "get_settings", lambda: safe_settings)
