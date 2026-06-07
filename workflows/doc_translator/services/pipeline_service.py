"""
src/services/pipeline_service.py
──────────────────────────────────
Orchestrates the full per-document flow:
  1. Download source blob + OCR  (single download, bytes reused)
  2. Translate OCR text to English (chunked REST API)
  3. Upload original binary to target as <stem>_en.<ext>
  4. LLM structured extraction on English text
  5. Upload extracted data as <stem>_en.json

Also exposes run_batch() for concurrent processing of all blobs in a container.

NOTE: The Azure Document Translation SDK (begin_translation) is intentionally
NOT used here. That service is an async bulk-container job, not suitable for
per-blob orchestration. We use the Translator REST API for text chunks instead.
"""

from __future__ import annotations

import json

from loggers.log_db import Step, Workflow, log_step
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Optional

from config.settings import settings
from shared.clients.blob_client import AzureBlobStorageClient
from shared.clients.doc_intel_client import AzureDocumentIntelligenceClient
from shared.clients.translator_client import AzureTranslatorClient
from workflows.doc_translator.services.extraction_service import ExtractionService
from workflows.doc_translator.services.ocr_service import OCRService
from workflows.doc_translator.services.translation_service import TranslationService
from shared.utils.blob_naming import extract_source_lang, json_blob_name, translated_blob_name

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

    # ── Public API ──────────────────────────────────────────────────────────

    def process_blob(
        self,
        blob_name: str,
        source_lang: str | None = None,
        skip_if_exists: bool = True,
        run_id: str = "doc-translator",
    ) -> DocumentResult:
        """
        Process a single blob end-to-end.

        Steps
        ─────
        1. Resolve source language from filename suffix (e.g. invoice_tr.pdf → 'tr'),
           falling back to caller-supplied source_lang, then auto-detect.
        2. Skip if target already exists (idempotent re-runs).
        3. Download source blob bytes + OCR in one shot.
        4. Translate OCR text to English.
        5. Upload original binary to target as <stem>_en.<ext>.
        6. LLM structured extraction on English text.
        7. Upload JSON to target as <stem>_en.json.
        """

        if hasattr(blob_name, "name"):
            blob_name = blob_name.name

        target_doc = translated_blob_name(blob_name)
        target_json = json_blob_name(blob_name)

        # Resolve source language: filename suffix > caller arg > auto-detect
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

            # ── Step 2: Download + OCR (single download, bytes reused) ─────
            source_bytes, extracted_text = self._ocr.extract_text(
                settings.source_container, blob_name
            )
            if not source_bytes:
                raise ValueError("Downloaded blob is empty")
            if not extracted_text:
                raise ValueError(
                    "OCR returned no text — document may be a scanned image "
                    "without readable content"
                )
            logger.info("OCR extracted %d characters", len(extracted_text))

            # ── Step 3: Translate OCR text to English ──────────────────────
            translated_text = self._translation.translate(
                extracted_text, source_lang=effective_lang
            )
            logger.info("Translated text: %d characters", len(translated_text))

            # ── Step 4: Upload original binary as <stem>_en.<ext> ──────────
            self._blob.upload(
                container=settings.target_container,
                blob_name=target_doc,
                data=source_bytes,
                content_type=_guess_content_type(blob_name),
            )
            logger.info("Document uploaded → %s", target_doc)

            # ── Step 5: LLM structured extraction ─────────────────────────
            logger.info("Running LLM extraction…")
            extracted_data = self._extraction.extract(translated_text)
            logger.info(
                "Extraction returned %d field(s): %s",
                len(extracted_data),
                list(extracted_data.keys()) if extracted_data else "[]",
            )

            if not extracted_data:
                logger.warning(
                    "LLM extraction returned empty result for %s — "
                    "check LLM_ENDPOINT, LLM_API_KEY, LLM_DEPLOYMENT_NAME in .env",
                    blob_name,
                )

            # ── Step 6: Upload JSON (always, even if extraction is partial) ─
            json_bytes = json.dumps(
                extracted_data, ensure_ascii=False, indent=2
            ).encode("utf-8")
            self._blob.upload(
                container=settings.target_container,
                blob_name=target_json,
                data=json_bytes,
                content_type="application/json",
            )
            logger.info("JSON uploaded → %s  (%d bytes)", target_json, len(json_bytes))

            # ── Lineage: translation + extraction completed ────────────────
            log_step(
                run_id=run_id,
                workflow_name=Workflow.DOC_TRANSLATOR,
                step_name=Step.TRANSLATION_COMPLETED,
                status="Completed",
                step_value=blob_name,
                detail=f"translated={target_doc}",
            )
            log_step(
                run_id=run_id,
                workflow_name=Workflow.DOC_TRANSLATOR,
                step_name=Step.EXTRACTION_COMPLETED,
                status="Completed",
                step_value=blob_name,
                detail=f"json={target_json} fields={len(extracted_data)}",
            )

            return DocumentResult(
                blob_name=blob_name,
                success=True,
                translated_blob=target_doc,
                json_blob=target_json,
                extracted_data=extracted_data,
            )

        except Exception as exc:
            logger.exception("Failed to process blob %s: %s", blob_name, exc)
            # ── Lineage: translation failed ───────────────────────────────
            log_step(
                run_id=run_id,
                workflow_name=Workflow.DOC_TRANSLATOR,
                step_name=Step.TRANSLATION_FAILED,
                status="Failed",
                step_value=blob_name,
                detail=str(exc),
            )
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
        run_id: str = "doc-translator",
    ) -> list[DocumentResult]:
        """
        List all blobs in the source container and process them concurrently.
        """
        workers = concurrency or settings.pipeline_concurrency
        blobs = list(self._blob.list_blobs(settings.source_container))

        if not blobs:
            logger.warning(
                "No blobs found in source container '%s'", settings.source_container
            )
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
                    self.process_blob, blob, source_lang, skip_if_exists, run_id
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
    ext = PurePosixPath(blob_name).suffix.lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")
