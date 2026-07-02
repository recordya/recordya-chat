from src.core.config import Settings


def test_default_locale_defaults_to_english(monkeypatch) -> None:
    monkeypatch.delenv("DEFAULT_LOCALE", raising=False)
    assert Settings(_env_file=None).DEFAULT_LOCALE == "en"


def test_default_locale_accepts_supported_languages() -> None:
    assert Settings(DEFAULT_LOCALE="en").DEFAULT_LOCALE == "en"
    assert Settings(DEFAULT_LOCALE="pl").DEFAULT_LOCALE == "pl"


def test_default_locale_normalizes_unknown_values_to_english() -> None:
    assert Settings(DEFAULT_LOCALE="de").DEFAULT_LOCALE == "en"
    assert Settings(DEFAULT_LOCALE=" PL ").DEFAULT_LOCALE == "pl"
