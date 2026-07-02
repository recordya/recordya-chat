"""Persisted application settings and the LLM model catalog.

Single source of truth for the list of selectable LLM models and for reading
and writing global key-value settings (e.g. the active model) backed by the
``system_settings`` table.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.db.models import SystemSetting

LLM_MODEL_KEY = "llm_model"


@dataclass(frozen=True)
class ModelOption:
    """A selectable LLM model."""

    id: str
    name: str


AVAILABLE_MODELS: tuple[ModelOption, ...] = (
    ModelOption("gpt-5.5", "GPT-5.5"),
    ModelOption("gpt-5.4", "GPT-5.4"),
    ModelOption("gpt-5.4-mini", "GPT-5.4 Mini"),
    ModelOption("gpt-5.4-nano", "GPT-5.4 Nano"),
    ModelOption("gpt-5.2", "GPT-5.2"),
    ModelOption("gpt-5", "GPT-5"),
    ModelOption("gpt-5-mini", "GPT-5 Mini"),
    ModelOption("gpt-5-nano", "GPT-5 Nano"),
    ModelOption("gpt-4o", "GPT-4o"),
    ModelOption("gpt-4o-mini", "GPT-4o Mini"),
)


def is_known_model(model_id: str) -> bool:
    """Return True if ``model_id`` is part of the available model catalog."""
    return any(option.id == model_id for option in AVAILABLE_MODELS)


async def get_setting(db: AsyncSession, key: str, default: str | None = None) -> str | None:
    """Read a single setting value, returning ``default`` when unset."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    """Insert or update a setting value."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))
    await db.flush()


async def get_selected_model(db: AsyncSession) -> str:
    """Return the active LLM model, falling back to the configured default."""
    value = await get_setting(db, LLM_MODEL_KEY, settings.DEFAULT_LLM_MODEL)
    return value or settings.DEFAULT_LLM_MODEL
