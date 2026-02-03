"""Factory functions for obtaining LLM providers.

This subpackage exposes a single helper, :func:`get_provider`, which
returns an instance of the requested LLM provider. Available providers
include ``mock`` (deterministic and offline), ``openai`` (which connects
to an OpenAI‑compatible API), and ``geode-ai`` (which provides Geode-specific
fuzzing patterns).
"""

from __future__ import annotations

from typing import Optional

from .base import LLMProvider
from .geode_ai import GeodeAIProvider
from .mock import MockProvider
from .openai_compat import OpenAICompatProvider


def get_provider(name: str, model: Optional[str] = None) -> LLMProvider:
    """Instantiate an LLM provider by name.

    Parameters
    ----------
    name:
        Name of the provider. Supported values are ``mock``, ``openai``, and ``geode-ai``.
    model:
        Optional model identifier passed through to the provider (only used
        by ``openai`` and ``geode-ai``).

    Returns
    -------
    LLMProvider
        An instance implementing the LLMProvider protocol.

    Raises
    ------
    ValueError
        If an unknown provider name is supplied.
    """
    norm = (name or "").strip().lower()
    if norm in {"mock", "none"}:
        return MockProvider()  # type: ignore[return-value]
    if norm in {"openai", "openai_compat"}:
        return OpenAICompatProvider(model=model)  # type: ignore[return-value]
    if norm in {"geode-ai", "geode_ai", "geodai"}:
        return GeodeAIProvider(model=model)  # type: ignore[return-value]
    raise ValueError(f"Unknown LLM provider: {name}")
