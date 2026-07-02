from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import auth as auth_routes
from src.core.config import Settings
from src.core.i18n import translate
from src.core.locales.en import MESSAGES as EN_MESSAGES
from src.core.locales.pl import MESSAGES as PL_MESSAGES


def test_backend_catalogs_have_matching_keys() -> None:
    assert set(PL_MESSAGES) == set(EN_MESSAGES)


def test_translate_falls_back_to_english_for_unknown_locale() -> None:
    assert translate("agent.status.default", locale="de") == EN_MESSAGES["agent.status.default"]


def test_translate_returns_raw_key_for_unknown_message() -> None:
    assert translate("missing.key", locale="pl") == "missing.key"


def test_auth_config_exposes_normalized_locale(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/auth")
    monkeypatch.setattr(auth_routes, "settings", Settings(AUTH_MODE="local", DEFAULT_LOCALE=" PL "))

    response = TestClient(app).get("/auth/config")

    assert response.status_code == 200
    assert response.json()["locale"] == "pl"


def _read_properties(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0].strip())
    return keys


def test_keycloak_message_catalogs_have_matching_keys() -> None:
    theme_root = Path(__file__).parents[2] / "keycloak" / "themes" / "recordya"
    for area in ["login", "email"]:
        messages_dir = theme_root / area / "messages"
        assert _read_properties(messages_dir / "messages_pl.properties") == _read_properties(
            messages_dir / "messages_en.properties"
        )
