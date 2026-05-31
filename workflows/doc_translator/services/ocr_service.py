"""
src/services/ocr_service.py
────────────────────────────
Coordinates downloading a blob and running OCR via Document Intelligence.
"""

from __future__ import annotations

import logging

from shared.clients.blob_client import AzureBlobStorageClient
from shared.clients.doc_intel_client import AzureDocumentIntelligenceClient

logger = logging.getLogger(__name__)


class OCRService:
    def __init__(
        self,
        blob_client: AzureBlobStorageClient,
        doc_intel_client: AzureDocumentIntelligenceClient,
    ) -> None:
        self._blob = blob_client
        self._doc_intel = doc_intel_client

    def extract_text(self, container: str, blob_name: str) -> tuple[bytes, str]:
        """
        Download *blob_name* from *container*, run OCR, and return both the
        raw bytes and the extracted text so callers avoid a second download.

        Returns
        -------
        (raw_bytes, extracted_text)
        """
        logger.info("Downloading + OCR: %s/%s", container, blob_name)
        raw_bytes = self._blob.download_blob_bytes(container, blob_name)

        if not raw_bytes:
            logger.warning("Blob %s/%s is empty; skipping OCR", container, blob_name)
            return b"", ""

        text = self._doc_intel.extract_text_from_bytes(raw_bytes)
        return raw_bytes, text

    def extract_text_from_bytes(self, raw_bytes: bytes) -> str:
        """Run OCR on already-downloaded bytes."""
        return self._doc_intel.extract_text_from_bytes(raw_bytes)
