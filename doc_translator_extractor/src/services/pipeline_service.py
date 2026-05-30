"""
src/services/pipeline_service.py
──────────────────────────────────
Orchestrates the full per-document flow:
  1. Download source blob bytes
  2. OCR  →  3. Translate text (chunked REST API)
  4. Upload original binary to target container as <filename>_en.<ext>
  5. LLM structured extraction on the English text
  6. Upload extracted JSON as <filename>_en.json

Also exposes run_batch() for concurrent processing of all blobs in a container.

NOTE: The Azure Document Translation SDK (begin_translation) is intentionally
NOT used here. That service translates whole containers asynchronously and
requires a dedicated Translator resource endpoint — it is not suitable for
per-file, per-blob orchestration. Instead we:
  • use the Translator REST API for text-chunk translation (OCR output)
  • copy the original binary file to the target container under the _en name
    (the PDF itself is the source of record; the JSON carries the English data)
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

from config.settings import settings
from src.clients.blob_client import AzureBlobStorageClient
from src.clients.doc_intel_client import AzureDocumentIntelligenceClient
from src.clients.translator_client import AzureTranslatorClient
from src.services.extraction_service import ExtractionService
from src.services.ocr_service import OCRService
from src.services.translation_service import TranslationService
from src.utils.blob_naming import extract_source_lang, json_blob_name, translated_blob_name

logger = logging.getLogger(__name__)


@dataclass
class DocumentResult:
    blob_name: str
    success: bool
    translated_blob: Optional[str] = None
    json_blob: Optional[str] = None
    error: Optional[str] = None
    extracted_data: dict = field(default_factory=dict)


class PipelineService:
    """End-to-end document translation and extraction pipeline."""

    def __init__(
        self,
        blob_client: AzureBlobStorageClient,
        doc_intel_client: AzureDocumentIntelligenceClient,
        translator_client: AzureTranslatorClient,
        extraction_service: ExtractionService,
    ) -> None:
        self._blob = blob_client
        self._ocr = OCRService(blob_client, doc_intel_client)
        self._translation = TranslationService(translator_client)
        self._extraction = extraction_service
        # NOTE: translator_client is used by TranslationService (text chunks).
        # The Document Translation SDK (begin_translation) is not used — see module docstring.

    # ── Public API ──────────────────────────────────────────────────────────

    def process_blob(
        self,
        blob_name: str,
        source_lang: str | None = None,
        skip_if_exists: bool = True,
    ) -> DocumentResult:
        """
        Process a single blob end-to-end.

        Steps
        ─────
        1. Skip if target already exists (idempotent re-runs).
        2. Download source blob bytes.
        3. OCR the document bytes via Document Intelligence.
        4. Translate the OCR text to English via Translator REST API.
        5. Upload the original binary to the target container as <stem>_en.<ext>.
        6. Run LLM structured extraction on the English text.
        7. Upload the extracted data as <stem>_en.json to the target container.

        Parameters
        ----------
        blob_name      : Name of the blob in the source container.
        source_lang    : BCP-47 language code, or None for auto-detect.
        skip_if_exists : If True and the target blob already exists, skip.

        Returns
        -------
        DocumentResult
        """
        target_doc = translated_blob_name(blob_name)
        target_json = json_blob_name(blob_name)

        # Resolve source language: filename suffix takes priority over the
        # caller-supplied value; fall back to None (auto-detect) if neither.
        detected_lang = extract_source_lang(blob_name)
        effective_lang = detected_lang or source_lang
        logger.info(
            "Processing blob: %s  (detected_lang=%s, effective_lang=%s)",
            blob_name,
            detected_lang or "—",
            effective_lang or "auto",
        )

        try:
            # ── Step 1: Skip if already done ───────────────────────────────
            if skip_if_exists and self._blob.blob_exists(
                settings.target_container, target_doc
            ):
                logger.info("Skipping %s — already exists in target", blob_name)
                return DocumentResult(
                    blob_name=blob_name,
                    success=True,
                    translated_blob=target_doc,
                    json_blob=target_json,
                )

            # ── Step 2: Download source bytes ──────────────────────────────
            source_bytes = self._blob.download_blob_bytes(
                settings.source_container, blob_name
            )

            # ── Step 3: OCR ────────────────────────────────────────────────
            extracted_text = self._ocr.extract_text(
                settings.source_container, blob_name
            )
            if not extracted_text:
                raise ValueError("OCR returned no text for blob")

            # ── Step 4: Translate OCR text to English ──────────────────────
            translated_text = self._translation.translate(
                extracted_text, source_lang=effective_lang
            )

            # ── Step 5: Upload original binary as <stem>_en.<ext> ──────────
            #    The PDF is the source of record. We copy it to the target
            #    container under the _en name so consumers can always find
            #    both the document and its JSON side-by-side.
            self._blob.upload_blob(
                container=settings.target_container,
                blob_name=target_doc,
                data=source_bytes,
                content_type=_guess_content_type(blob_name),
            )
            logger.info("Document uploaded → %s", target_doc)

            # ── Step 6: LLM structured extraction ─────────────────────────
            extracted_data = self._extraction.extract(translated_text)

            # ── Step 7: Upload JSON ────────────────────────────────────────
            json_bytes = json.dumps(
                extracted_data, ensure_ascii=False, indent=2
            ).encode("utf-8")
            self._blob.upload_blob(
                container=settings.target_container,
                blob_name=target_json,
                data=json_bytes,
                content_type="application/json",
            )
            logger.info("JSON uploaded → %s", target_json)

            return DocumentResult(
                blob_name=blob_name,
                success=True,
                translated_blob=target_doc,
                json_blob=target_json,
                extracted_data=extracted_data,
            )

        except Exception as exc:
            logger.exception("Failed to process blob %s: %s", blob_name, exc)
            return DocumentResult(
                blob_name=blob_name,
                success=False,
                error=str(exc),
            )

    def run_batch(
        self,
        source_lang: str | None = None,
        concurrency: int | None = None,
        skip_if_exists: bool = True,
    ) -> list[DocumentResult]:
        """
        List all blobs in the source container and process them concurrently.

        Parameters
        ----------
        source_lang    : BCP-47 language code, or None for auto-detect.
        concurrency    : Max parallel workers. Defaults to settings value.
        skip_if_exists : Skip blobs whose translated counterpart already exists.

        Returns
        -------
        list[DocumentResult] : One result per blob, in completion order.
        """
        workers = concurrency or settings.pipeline_concurrency
        blobs = list(self._blob.list_blobs(settings.source_container))

        if not blobs:
            logger.warning("No blobs found in source container '%s'", settings.source_container)
            return []

        logger.info(
            "Batch starting — %d blobs, concurrency=%d, source_lang=%s",
            len(blobs),
            workers,
            source_lang or "auto",
        )

        results: list[DocumentResult] = []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_blob = {
                executor.submit(
                    self.process_blob, blob, source_lang, skip_if_exists
                ): blob
                for blob in blobs
            }

            for future in as_completed(future_to_blob):
                result = future.result()
                results.append(result)
                status = "✓" if result.success else "✗"
                logger.info("%s %s", status, result.blob_name)

        succeeded = sum(1 for r in results if r.success)
        failed = len(results) - succeeded
        logger.info("Batch complete — %d succeeded, %d failed", succeeded, failed)

        return results


# ── Helpers ─────────────────────────────────────────────────────────────────

_CONTENT_TYPES: dict[str, str] = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc":  "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif":  "image/tiff",
}


def _guess_content_type(blob_name: str) -> str:
    from pathlib import PurePosixPath
    ext = PurePosixPath(blob_name).suffix.lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")
