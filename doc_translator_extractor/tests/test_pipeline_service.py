"""
tests/test_pipeline_service.py
────────────────────────────────
Integration-style unit tests for PipelineService — all Azure calls are mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

from config.settings import settings
from src.services.pipeline_service import DocumentResult, PipelineService


def _make_pipeline(
    *,
    blob_exists: bool = False,
    ocr_text: str = "Invoice text",
    translated_text: str = "Translated text",
    extracted_data: dict | None = None,
) -> PipelineService:
    """Wire up a PipelineService with all dependencies mocked."""
    blob_client = MagicMock()
    blob_client.blob_exists.return_value = blob_exists
    blob_client.download_blob_bytes.return_value = b"%PDF fake bytes"
    blob_client.get_container_sas_url.return_value = "https://mock-sas-url"

    doc_intel = MagicMock()
    doc_intel.extract_text_from_bytes.return_value = ocr_text

    translator = MagicMock()
    translator.translate_text.return_value = translated_text
    translator.translate_document.return_value = [{"id": "abc", "status": "Succeeded", "error": None}]

    extraction = MagicMock()
    extraction.extract.return_value = extracted_data or {"invoiceNumber": "123"}

    # Patch OCRService and TranslationService to avoid settings validation
    pipeline = PipelineService(
        blob_client=blob_client,
        doc_intel_client=doc_intel,
        translator_client=translator,
        extraction_service=extraction,
    )
    # Override internal services with mocks for simplicity
    pipeline._ocr = MagicMock()
    pipeline._ocr.extract_text.return_value = ocr_text
    pipeline._translation = MagicMock()
    pipeline._translation.translate.return_value = translated_text

    return pipeline


def test_process_blob_success():
    pipeline = _make_pipeline()
    result = pipeline.process_blob("invoice.pdf", source_lang=None, skip_if_exists=False)

    assert result.success is True
    assert result.translated_blob == "invoice_en.pdf"
    assert result.json_blob == "invoice_en.json"
    assert result.error is None


def test_process_blob_skip_when_exists():
    pipeline = _make_pipeline(blob_exists=True)
    result = pipeline.process_blob("invoice.pdf", skip_if_exists=True)

    assert result.success is True
    # OCR should NOT have been called
    pipeline._ocr.extract_text.assert_not_called()


def test_process_blob_ocr_returns_empty():
    pipeline = _make_pipeline(ocr_text="")
    result = pipeline.process_blob("invoice.pdf", skip_if_exists=False)

    assert result.success is False
    assert "no text" in result.error.lower()


def test_process_blob_captures_exception():
    pipeline = _make_pipeline()
    pipeline._ocr.extract_text.side_effect = RuntimeError("OCR service unavailable")

    result = pipeline.process_blob("invoice.pdf", skip_if_exists=False)

    assert result.success is False
    assert "OCR service unavailable" in result.error


def test_run_batch_returns_results():
    pipeline = _make_pipeline()
    pipeline._blob.list_blobs.return_value = iter(["a.pdf", "b.pdf"])

    results = pipeline.run_batch(source_lang=None, concurrency=2, skip_if_exists=False)

    assert len(results) == 2
    assert all(r.success for r in results)
