"""Backend-side localization.

The locale is static and config-driven: it is taken from
``settings.DEFAULT_LOCALE`` (a single source of truth shared with the frontend
and Keycloak). There is no per-request language negotiation.

Usage::

    from src.core.i18n import translate
    translate("agent.error.generic")
    translate("chat.error.rate_limit", limit=20)
"""

from src.core.config import settings
from src.core.locales.en import MESSAGES as EN_MESSAGES
from src.core.locales.pl import MESSAGES as PL_MESSAGES

_CATALOGS: dict[str, dict[str, str]] = {
    "en": EN_MESSAGES,
    "pl": PL_MESSAGES,
}

_FALLBACK_LOCALE = "en"


def translate(key: str, *, locale: str | None = None, **params: object) -> str:
    """Return the localized message for ``key``.

    Resolves the locale from ``settings.DEFAULT_LOCALE`` unless ``locale`` is
    given. Falls back to English, then to the raw ``key`` if the message id is
    unknown. ``params`` are substituted via ``str.format``.
    """
    resolved = (locale or settings.DEFAULT_LOCALE or _FALLBACK_LOCALE).lower()
    catalog = _CATALOGS.get(resolved, _CATALOGS[_FALLBACK_LOCALE])
    template = catalog.get(key) or _CATALOGS[_FALLBACK_LOCALE].get(key) or key
    if params:
        try:
            return template.format(**params)
        except (KeyError, IndexError, ValueError):
            return template
    return template
