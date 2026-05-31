"""
workflows/email_scanner/services/attachment_processor.py
──────────────────────────────────────────────────────────
Processes a single email attachment end-to-end:
  1. OCR via Document Intelligence
  2. Translate to English via Translator REST API
  3. Classify as invoice or not via LLM
  4. If valid: detect source language → upload to raw-invoice container
     as <stem>_<langcode>.<ext>
  5. If invalid: upload to invalid-invoice container as-is
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePosixPath

from config.settings import settings
from shared.utils.blob_naming import raw_invoice_blob_name
from shared.clients.blob_client import AzureBlobStorageClient
from shared.clients.doc_intel_client import AzureDocumentIntelligenceClient
from shared.clients.translator_client import AzureTranslatorClient
from workflows.email_scanner.services.invoice_classifier import InvoiceClassifier
from workflows.email_scanner.services.language_detector import LanguageDetector
from workflows.doc_translator.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

_CONTENT_TYPES: dict[str, str] = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc":  "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".tiff": "image/tiff",
    ".tif":  "image/tiff",
}


@dataclass
class AttachmentResult:
    filename: str
    is_valid: bool
    blob_name: str | None       # where it was stored
    container: str | None       # which container
    lang_code: str | None       # detected language code
    reason: str                 # classification reason (always filled)
    ocr_text: str = ""


def _stem_and_ext(filename: str) -> tuple[str, str]:
    p = PurePosixPath(filename)
    return p.stem, p.suffix.lower()


def _content_type(filename: str) -> str:
    ext = PurePosixPath(filename).suffix.lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


class AttachmentProcessor:
    def __init__(
        self,
        blob_client: AzureBlobStorageClient,
        doc_intel_client: AzureDocumentIntelligenceClient,
        translator_client: AzureTranslatorClient,
        classifier: InvoiceClassifier,
        language_detector: LanguageDetector,
    ) -> None:
        self._blob = blob_client
        self._doc_intel = doc_intel_client
        self._translation = TranslationService(translator_client)
        self._classifier = classifier
        self._lang_detector = language_detector

    def process(self, filename: str, raw_bytes: bytes) -> AttachmentResult:
        """
        Full pipeline for one attachment.

        Parameters
        ----------
        filename  : Original attachment filename.
        raw_bytes : Raw file content downloaded from the email.

        Returns
        -------
        AttachmentResult
        """
        stem, ext = _stem_and_ext(filename)
        logger.info("Processing attachment: %s (%d bytes)", filename, len(raw_bytes))

        try:
            # ── Step 1: OCR ────────────────────────────────────────────────
            ocr_text = self._doc_intel.extract_text_from_bytes(raw_bytes)
            if not ocr_text.strip():
                return AttachmentResult(
                    filename=filename,
                    is_valid=False,
                    blob_name=None,
                    container=None,
                    lang_code=None,
                    reason="Document appears to be empty or contains no readable text (possibly a scanned image without OCR layer).",
                )
            logger.info("OCR: %d characters extracted from %s", len(ocr_text), filename)

            # ── Step 2: Detect source language from OCR text ───────────────
            lang_code = self._lang_detector.detect(ocr_text) or "xx"
            logger.info("Language detected for %s: %s", filename, lang_code)

            # ── Step 3: Translate to English ───────────────────────────────
            if lang_code != "en" and lang_code != "xx":
                translated_text = self._translation.translate(
                    ocr_text, source_lang=lang_code
                )
            else:
                translated_text = ocr_text
            logger.info("Translation complete for %s", filename)

            # ── Step 4: Classify ───────────────────────────────────────────
            classification = self._classifier.classify(translated_text, filename)
            is_invoice = classification.get("is_invoice", False)
            reason = classification.get("reason", "No reason provided.")

            # ── Step 5: Upload to correct container ────────────────────────
            if is_invoice:
                # Name format: <stem>_<langcode><ext>  e.g. invoice_tr.pdf
                target_name = raw_invoice_blob_name(filename, lang_code)
                container = settings.raw_invoice_container
            else:
                # Store rejected file as-is for audit
                target_name = filename
                container = settings.invalid_invoice_container

            self._blob.upload_blob(
                container=container,
                blob_name=target_name,
                data=raw_bytes,
                content_type=_content_type(filename),
            )
            logger.info(
                "%s → %s/%s (valid=%s)",
                filename, container, target_name, is_invoice,
            )

            return AttachmentResult(
                filename=filename,
                is_valid=is_invoice,
                blob_name=target_name,
                container=container,
                lang_code=lang_code,
                reason=reason,
                ocr_text=ocr_text,
            )

        except Exception as exc:
            logger.exception("Failed to process attachment %s: %s", filename, exc)
            # Best-effort: try to store in invalid container for audit
            try:
                self._blob.upload_blob(
                    container=settings.invalid_invoice_container,
                    blob_name=filename,
                    data=raw_bytes,
                    content_type=_content_type(filename),
                )
            except Exception:
                pass

            return AttachmentResult(
                filename=filename,
                is_valid=False,
                blob_name=filename,
                container=settings.invalid_invoice_container,
                lang_code=None,
                reason=f"Processing error: {exc}",
            )
