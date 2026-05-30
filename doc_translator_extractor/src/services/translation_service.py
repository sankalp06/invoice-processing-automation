"""
src/services/translation_service.py
─────────────────────────────────────
Handles text chunking and chunk-by-chunk translation.
Provides a fallback to auto-detect if a specified source language fails.
"""

from __future__ import annotations

import logging

from config.settings import settings
from src.clients.translator_client import AzureTranslatorClient

logger = logging.getLogger(__name__)


class TranslationService:
    def __init__(self, translator_client: AzureTranslatorClient) -> None:
        self._client = translator_client
        self._chunk_size = settings.translation_chunk_size

    def translate(self, text: str, source_lang: str | None = None) -> str:
        """
        Translate *text* to English, chunking as needed.

        Parameters
        ----------
        text        : Raw text to translate.
        source_lang : Optional BCP-47 language code. If None, auto-detect is used.

        Returns
        -------
        str : Translated text.
        """
        if not text:
            return ""

        chunks = self._chunk(text)
        logger.info(
            "Translating %d chunk(s) (source_lang=%s)",
            len(chunks),
            source_lang or "auto",
        )

        translated: list[str] = []
        for idx, chunk in enumerate(chunks, start=1):
            logger.debug("Translating chunk %d/%d", idx, len(chunks))
            result = self._translate_chunk_with_fallback(chunk, source_lang)
            translated.append(result)

        final = "\n".join(translated)
        logger.info("Translation complete — output %d characters", len(final))
        return final

    # ── Private helpers ─────────────────────────────────────────────────────

    def _chunk(self, text: str) -> list[str]:
        """Split *text* into chunks no larger than *chunk_size* characters."""
        size = self._chunk_size
        return [text[i : i + size] for i in range(0, len(text), size)]

    def _translate_chunk_with_fallback(
        self, chunk: str, source_lang: str | None
    ) -> str:
        """
        Attempt translation with *source_lang*; fall back to auto-detect on error.
        """
        try:
            return self._client.translate_text(chunk, source_lang=source_lang)
        except Exception as primary_exc:
            if source_lang is None:
                raise  # Already auto-detect; nothing to fall back to

            logger.warning(
                "Translation with source_lang=%s failed (%s). "
                "Retrying with auto-detect.",
                source_lang,
                primary_exc,
            )
            return self._client.translate_text(chunk, source_lang=None)
