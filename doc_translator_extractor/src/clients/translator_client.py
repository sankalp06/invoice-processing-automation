"""
src/clients/translator_client.py
─────────────────────────────────
Wraps both:
  • Azure Translator REST API  — for text-chunk translation
  • Azure Document Translation SDK — for full-document (binary) translation
"""

from __future__ import annotations

import logging

import requests
from azure.ai.translation.document import DocumentTranslationClient
from azure.core.credentials import AzureKeyCredential

from config.settings import settings
from src.utils.retry import retry

logger = logging.getLogger(__name__)

_TRANSLATE_ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"


class AzureTranslatorClient:
    """Handles text and document translation using Azure Cognitive Services."""

    def __init__(self) -> None:
        self._key = settings.translator_key
        self._region = settings.translator_region
        self._doc_client = DocumentTranslationClient(
            endpoint=settings.translator_endpoint,
            credential=AzureKeyCredential(self._key),
        )

    # ── Text translation ────────────────────────────────────────────────────

    @retry(max_attempts=3, base_delay=1.0, exceptions=(requests.HTTPError, Exception))
    def translate_text(self, text: str, source_lang: str | None = None) -> str:
        """
        Translate a single text string to English.

        Parameters
        ----------
        text        : The text to translate (max ~10 000 chars).
        source_lang : BCP-47 language code of the source, or None for auto-detect.

        Returns
        -------
        str : Translated text.
        """
        params: dict[str, str] = {"api-version": "3.0", "to": "en"}
        if source_lang:
            params["from"] = source_lang

        headers = {
            "Ocp-Apim-Subscription-Key": self._key,
            "Ocp-Apim-Subscription-Region": self._region,
            "Content-Type": "application/json",
        }

        response = requests.post(
            _TRANSLATE_ENDPOINT,
            params=params,
            headers=headers,
            json=[{"text": text}],
            timeout=30,
        )
        response.raise_for_status()

        result = response.json()
        return result[0]["translations"][0]["text"]

    # ── Document translation (binary) ───────────────────────────────────────

    def translate_document(
        self,
        source_container_url: str,
        target_container_url: str,
        source_lang: str | None = None,
    ) -> list[dict]:
        """
        Submit a batch document translation job and wait for completion.

        Parameters
        ----------
        source_container_url : SAS URL for the source container.
        target_container_url : SAS URL for the target container.
        source_lang          : BCP-47 language code, or None for auto-detect.

        Returns
        -------
        list[dict] : Per-document status dicts with keys id, status, error.
        """
        logger.info(
            "Starting document translation batch (source_lang=%s)",
            source_lang or "auto",
        )

        poller = self._doc_client.begin_translation(
            source_url=source_container_url,
            target_url=target_container_url,
            target_language="en",
            **({"source_language": source_lang} if source_lang else {}),
        )

        results = []
        for doc in poller.result():
            entry = {
                "id": doc.id,
                "status": str(doc.status),
                "error": (
                    {"code": doc.error.code, "message": doc.error.message}
                    if doc.error
                    else None
                ),
            }
            results.append(entry)
            if doc.error:
                logger.error(
                    "Document %s failed: [%s] %s",
                    doc.id,
                    doc.error.code,
                    doc.error.message,
                )
            else:
                logger.info("Document %s succeeded", doc.id)

        return results
