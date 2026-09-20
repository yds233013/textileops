"""Provider selection.

``AI_PROVIDER=auto`` (the default) uses Anthropic when a key is configured and
the deterministic stub otherwise. The application never fails because AI is
unavailable; it degrades to rules and says so.
"""

from __future__ import annotations

from functools import lru_cache

from textileops.ai.base import AIProvider
from textileops.ai.stub_provider import StubProvider
from textileops.core.config import settings
from textileops.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_provider() -> AIProvider:
    if settings.ai_provider == "stub" or not settings.anthropic_api_key:
        if settings.ai_provider == "anthropic":
            logger.warning(
                "ai_provider_downgraded",
                reason="AI_PROVIDER=anthropic but no ANTHROPIC_API_KEY is configured",
            )
        logger.info("ai_provider_selected", provider="stub")
        return StubProvider()

    from textileops.ai.anthropic_provider import AnthropicProvider

    logger.info("ai_provider_selected", provider="anthropic", model=settings.ai_model)
    return AnthropicProvider()


def reset_provider_cache() -> None:
    get_provider.cache_clear()
