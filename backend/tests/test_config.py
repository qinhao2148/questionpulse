from app.core.config import Settings


def test_blank_llm_environment_values_use_safe_defaults() -> None:
    settings = Settings(llm_base_url="", llm_model="")
    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-flash"
