"""Factory functions for creating core services.

Creates engine with configured observability and other services.
"""

import logging
from typing import TYPE_CHECKING

from src.core.config import settings
from src.core.engine import CoreEngine
from src.llm.client import get_llm_facade
from src.services.observability import NoOpObservabilityProvider, ObservabilityProvider

if TYPE_CHECKING:
    from src.llm.client import LlmFacade

logger = logging.getLogger(__name__)


def create_observability_provider() -> ObservabilityProvider:
    """Create observability provider based on settings.
    
    Returns:
        Configured observability provider or no-op if disabled
    """
    provider = settings.OBSERVABILITY_PROVIDER
    
    if provider == "langfuse" and settings.LANGFUSE_ENABLED:
        try:
            from src.services.providers.langfuse_provider import (
                LangfuseObservabilityProvider,
            )
            
            logger.info("Using Langfuse observability provider")
            return LangfuseObservabilityProvider(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST if settings.LANGFUSE_HOST else None,
                environment=settings.ENV,
            )
        except Exception as e:
            logger.warning(f"Failed to create Langfuse provider: {e}")
    
    logger.info("Observability disabled, using no-op provider")
    return NoOpObservabilityProvider()


def create_engine(llm_client: "LlmFacade | None" = None) -> CoreEngine:
    """Factory - creates engine with configured services.
    
    Args:
        llm_client: Optional LLM client (defaults to singleton)
        
    Returns:
        Configured CoreEngine instance
    """
    # Get LLM client
    if llm_client is None:
        llm_client = get_llm_facade()
    
    # Create observability provider
    observability = create_observability_provider()
    
    return CoreEngine(
        llm_client=llm_client,
        tool_registry={},  # Tools are managed by plugins
        state_store={},
        observability=observability,
    )


# Singleton engine instance
_engine: CoreEngine | None = None


def get_engine() -> CoreEngine:
    """Get the singleton CoreEngine instance.
    
    Returns:
        CoreEngine singleton
    """
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def reset_engine() -> None:
    """Reset the singleton engine (for testing)."""
    global _engine
    _engine = None
