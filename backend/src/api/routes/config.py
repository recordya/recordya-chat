"""Global application configuration endpoints (admin-managed)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.api.dependencies import CurrentUser, DBSession
from src.core.exceptions import bad_request, forbidden
from src.core.roles import has_admin_privileges
from src.services.app_settings import (
    AVAILABLE_MODELS,
    LLM_MODEL_KEY,
    get_selected_model,
    is_known_model,
    set_setting,
)

router = APIRouter()


class ModelOptionResponse(BaseModel):
    """A selectable LLM model."""

    id: str
    name: str


class ModelConfigResponse(BaseModel):
    """Available models and the currently active selection."""

    available: list[ModelOptionResponse]
    selected: str


class UpdateModelRequest(BaseModel):
    """Admin request to change the active LLM model."""

    model: str = Field(..., min_length=1)


async def _build_response(db: DBSession) -> ModelConfigResponse:
    selected = await get_selected_model(db)
    return ModelConfigResponse(
        available=[
            ModelOptionResponse(id=option.id, name=option.name)
            for option in AVAILABLE_MODELS
        ],
        selected=selected,
    )


@router.get("/models", response_model=ModelConfigResponse)
async def get_model_config(
    current_user: CurrentUser,
    db: DBSession,
) -> ModelConfigResponse:
    """Return the model catalog and the active model (any authenticated user)."""
    return await _build_response(db)


@router.patch("/models", response_model=ModelConfigResponse)
async def update_model_config(
    request: UpdateModelRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> ModelConfigResponse:
    """Change the active LLM model (admin only)."""
    if not has_admin_privileges(current_user.role):
        raise forbidden("Admin role required")
    if not is_known_model(request.model):
        raise bad_request("Unknown model")

    await set_setting(db, LLM_MODEL_KEY, request.model)
    return await _build_response(db)
