"""
src/clients/doc_intel_client.py
────────────────────────────────
Thin wrapper around azure-ai-documentintelligence.
Accepts raw bytes or a SAS URL and returns the OCR result.
"""

from __future__ import annotations

import logging
from io import BytesIO

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential

from config.settings import settings
from src.utils.retry import retry

logger = logging.getLogger(__name__)


class AzureDocumentIntelligenceClient:
    """Wraps Azure Document Intelligence for OCR extraction."""

    def __init__(self) -> None:
        self._client = DocumentIntelligenceClient(
            endpoint=settings.doc_intelligence_endpoint,
            credential=AzureKeyCredential(settings.doc_intelligence_key),
        )
        self._model_id = settings.ocr_model

    @retry(max_attempts=3, base_delay=2.0, exceptions=(Exception,))
    def extract_text_from_bytes(self, document_bytes: bytes) -> str:
        """
        Run OCR on *document_bytes* and return the raw extracted text.
        Returns an empty string if nothing was extracted.
        """
        logger.info("Running OCR (model=%s) on %d bytes", self._model_id, len(document_bytes))

        poller = self._client.begin_analyze_document(
            model_id=self._model_id,
            body=BytesIO(document_bytes),
        )
        result = poller.result()
        text = (result.content or "").strip()

        logger.info("OCR extracted %d characters", len(text))
        return text

    @retry(max_attempts=3, base_delay=2.0, exceptions=(Exception,))
    def extract_text_from_url(self, sas_url: str) -> str:
        """
        Run OCR on a document reachable via *sas_url*.
        Returns the raw extracted text.
        """
        logger.info("Running OCR (model=%s) via URL", self._model_id)

        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

        poller = self._client.begin_analyze_document(
            model_id=self._model_id,
            body=AnalyzeDocumentRequest(url_source=sas_url),
        )
        result = poller.result()
        text = (result.content or "").strip()

        logger.info("OCR extracted %d characters", len(text))
        return text
