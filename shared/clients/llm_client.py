"""
src/clients/llm_client.py
──────────────────────────
OpenAI-compatible client for structured invoice extraction.
Works with Azure OpenAI and any OpenAI-compatible endpoint.
"""

from __future__ import annotations

import logging

from openai import OpenAI

from config.settings import settings

logger = logging.getLogger(__name__)


def create_llm_client() -> OpenAI:
    """Return a configured OpenAI client pointed at the LLM endpoint."""
    return OpenAI(
        base_url=settings.llm_endpoint,
        api_key=settings.llm_api_key,
    )
