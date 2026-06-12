"""
function_app.py
────────────────
Azure Functions entry point for the Invoice Processing Platform.

4 Workflows
───────────
1. OCR Pipeline     raw-invoices → ocr-invoices
                    workflows/ocr_pipeline.py :: process_files()

2. Email Scanner    Inbox → raw-invoices / invalid-invoices + vendor reply email
                    workflows/email_scanner/services/email_scanner_pipeline.py :: EmailScannerPipeline.run()

3. Doc Translator   ocr-invoices → translated-invoices + _en.json extraction
                    workflows/doc_translator/services/pipeline_service.py :: PipelineService.run_batch()

4. Lineage API      REST only — aggregated metrics from invoice_process_log
                    workflows/lineage_summary.py :: get_lineage_summary_response()

Endpoints
─────────
HTTP  POST/GET  ocr_trigger          → Workflow 1
HTTP  POST/GET  email_processing     → Workflow 2
HTTP  POST/GET  translation_trigger  → Workflow 3
HTTP  GET       lineage_summary      → Workflow 4

Timer  0 10,40 * * * *   ocr_timer           → Workflow 1  (every 30 min)
Timer  0 5,35  * * * *   email_timer         → Workflow 2  (every 30 min)
Timer  0 25,55 * * * *   translation_timer   → Workflow 3  (every 30 min)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import azure.functions as func
from dotenv import load_dotenv

from loggers.logging_setup import setup_logging
from loggers.log_db import Step, Workflow, log_step

# ── Bootstrap ──────────────────────────────────────────────────────────────────
setup_logging()
load_dotenv(override=True)

# ── Workflow 1: OCR Pipeline ───────────────────────────────────────────────────
from workflows.ocr_pipeline import process_files as run_ocr

# ── Workflow 2: Email Scanner ──────────────────────────────────────────────────
from shared.clients.blob_client import BlobStorageClient
from shared.clients.doc_intel_client import AzureDocumentIntelligenceClient
from shared.clients.graph_client import MSGraphClient
from shared.clients.translator_client import AzureTranslatorClient
from workflows.email_scanner.services.email_scanner_pipeline import EmailScannerPipeline

# ── Workflow 3: Doc Translator ─────────────────────────────────────────────────
from shared.clients.llm_client import create_llm_client
from workflows.doc_translator.services.extraction_service import ExtractionService
from workflows.doc_translator.services.pipeline_service import PipelineService

# ── Workflow 4: Lineage REST API ───────────────────────────────────────────────
from workflows.lineage_summary import get_lineage_summary_response, get_attachment_lineage_response

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}"


def _parse_lookback(req: func.HttpRequest, default: float) -> float:
    """Read lookback_hours from query param or JSON body; fall back to default."""
    raw = req.params.get("lookback_hours")
    if not raw:
        try:
            raw = (req.get_json(silent=True) or {}).get("lookback_hours")
        except Exception:
            pass
    if raw:
        try:
            return float(raw)
        except (ValueError, TypeError):
            logger.warning("Invalid lookback_hours '%s' — using default %s", raw, default)
    return default


def _ok(message: str) -> func.HttpResponse:
    return func.HttpResponse(message, status_code=200)


def _err(message: str, status_code: int = 500) -> func.HttpResponse:
    return func.HttpResponse(message, status_code=status_code)


def _json_ok(data: dict) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data, default=str),
        mimetype="application/json",
        status_code=200,
    )


def _build_email_scanner() -> EmailScannerPipeline:
    return EmailScannerPipeline(
        graph_client=MSGraphClient(),
        blob_client=BlobStorageClient(),
        doc_intel_client=AzureDocumentIntelligenceClient(),
        translator_client=AzureTranslatorClient(),
    )


def _build_doc_translator() -> PipelineService:
    return PipelineService(
        blob_client=BlobStorageClient(),
        doc_intel_client=AzureDocumentIntelligenceClient(),
        translator_client=AzureTranslatorClient(),
        extraction_service=ExtractionService(llm_client=create_llm_client()),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Workflow 1 — OCR Pipeline   (raw-invoices → ocr-invoices)
# ─────────────────────────────────────────────────────────────────────────────

@app.route(route="ocr_trigger", methods=["GET", "POST"])
def ocr_trigger(req: func.HttpRequest) -> func.HttpResponse:
    rid = _run_id("ocr-http")
    lookback = _parse_lookback(req, default=6.0)
    logger.info("ocr_trigger | run_id=%s lookback=%sh", rid, lookback)

    try:
        run_ocr(lookback_hours=lookback, run_id=rid)
        return _ok(f"OCR completed for the last {lookback}h. run_id={rid}")

    except Exception as exc:
        logger.error("ocr_trigger failed | run_id=%s | %s", rid, exc, exc_info=True)
        log_step(rid, Workflow.OCR_PIPELINE, Step.WORKFLOW_FAILED, "Failed", detail=str(exc))
        return _err(f"OCR failed: {exc}")


@app.timer_trigger(
    schedule="0 10,40 * * * *",
    arg_name="ocrTimer",
    run_on_startup=False,
    use_monitor=False,
)
def ocr_timer(ocrTimer: func.TimerRequest) -> None:
    rid = _run_id("ocr-timer")
    if ocrTimer.past_due:
        logger.warning("OCR timer past due | run_id=%s", rid)
    logger.info("OCR timer triggered | run_id=%s", rid)
    try:
        run_ocr(lookback_hours=0.5, run_id=rid)
    except Exception as exc:
        logger.error("OCR timer failed | run_id=%s | %s", rid, exc, exc_info=True)
        log_step(rid, Workflow.OCR_PIPELINE, Step.WORKFLOW_FAILED, "Failed", detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Workflow 2 — Email Scanner   (Inbox → raw-invoices / invalid-invoices)
# ─────────────────────────────────────────────────────────────────────────────

@app.route(route="email_processing", methods=["GET", "POST"])
def email_processing_trigger(req: func.HttpRequest) -> func.HttpResponse:
    rid = _run_id("email-http")
    lookback = _parse_lookback(req, default=1.0)
    logger.info("email_processing_trigger | run_id=%s lookback=%sh", rid, lookback)

    try:
        result = _build_email_scanner().run(lookback_hours=lookback, run_id=rid)
        log_step(
            rid, Workflow.EMAIL_SCANNER, Step.WORKFLOW_COMPLETED, "Completed",
            detail=(
                f"messages={result.messages_scanned} "
                f"valid={result.valid_invoices} "
                f"invalid={result.invalid_invoices}"
            ),
        )
        return _ok(
            f"Email processing completed. "
            f"Scanned={result.messages_scanned} "
            f"Valid={result.valid_invoices} "
            f"Invalid={result.invalid_invoices} "
            f"run_id={rid}"
        )

    except Exception as exc:
        logger.error("email_processing failed | run_id=%s | %s", rid, exc, exc_info=True)
        log_step(rid, Workflow.EMAIL_SCANNER, Step.WORKFLOW_FAILED, "Failed", detail=str(exc))
        return _err(f"Email processing failed: {exc}")


@app.timer_trigger(
    schedule="0 5,35 * * * *",
    arg_name="emailTimer",
    run_on_startup=False,
    use_monitor=False,
)
def email_timer(emailTimer: func.TimerRequest) -> None:
    from config.settings import settings
    rid = _run_id("email-timer")
    if emailTimer.past_due:
        logger.warning("Email timer past due | run_id=%s", rid)
    lookback = settings.timer_lookback_hours
    logger.info("Email timer triggered | run_id=%s lookback=%sh", rid, lookback)
    try:
        result = _build_email_scanner().run(lookback_hours=lookback, run_id=rid)
        log_step(
            rid, Workflow.EMAIL_SCANNER, Step.WORKFLOW_COMPLETED, "Completed",
            detail=(
                f"messages={result.messages_scanned} "
                f"valid={result.valid_invoices} "
                f"invalid={result.invalid_invoices}"
            ),
        )
    except Exception as exc:
        logger.error("Email timer failed | run_id=%s | %s", rid, exc, exc_info=True)
        log_step(rid, Workflow.EMAIL_SCANNER, Step.WORKFLOW_FAILED, "Failed", detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Workflow 3 — Doc Translator  (ocr-invoices → translated-invoices + JSON)
# ─────────────────────────────────────────────────────────────────────────────

@app.route(route="translation_trigger", methods=["GET", "POST"])
def translation_trigger(req: func.HttpRequest) -> func.HttpResponse:
    rid = _run_id("translation-http")
    source_lang = req.params.get("source_lang") or None
    logger.info("translation_trigger | run_id=%s source_lang=%s", rid, source_lang or "auto")

    try:
        results = _build_doc_translator().run_batch(source_lang=source_lang, run_id=rid)
        succeeded = sum(1 for r in results if r.success)
        failed    = len(results) - succeeded
        log_step(
            rid, Workflow.DOC_TRANSLATOR, Step.WORKFLOW_COMPLETED, "Completed",
            detail=f"total={len(results)} succeeded={succeeded} failed={failed}",
        )
        return _ok(
            f"Translation completed. "
            f"Total={len(results)} Succeeded={succeeded} Failed={failed} "
            f"run_id={rid}"
        )

    except Exception as exc:
        logger.error("translation_trigger failed | run_id=%s | %s", rid, exc, exc_info=True)
        log_step(rid, Workflow.DOC_TRANSLATOR, Step.WORKFLOW_FAILED, "Failed", detail=str(exc))
        return _err(f"Translation failed: {exc}")


@app.timer_trigger(
    schedule="0 25,55 * * * *",
    arg_name="translationTimer",
    run_on_startup=False,
    use_monitor=False,
)
def translation_timer(translationTimer: func.TimerRequest) -> None:
    rid = _run_id("translation-timer")
    if translationTimer.past_due:
        logger.warning("Translation timer past due | run_id=%s", rid)
    logger.info("Translation timer triggered | run_id=%s", rid)
    try:
        results = _build_doc_translator().run_batch(run_id=rid)
        succeeded = sum(1 for r in results if r.success)
        failed    = len(results) - succeeded
        log_step(
            rid, Workflow.DOC_TRANSLATOR, Step.WORKFLOW_COMPLETED, "Completed",
            detail=f"total={len(results)} succeeded={succeeded} failed={failed}",
        )
    except Exception as exc:
        logger.error("Translation timer failed | run_id=%s | %s", rid, exc, exc_info=True)
        log_step(rid, Workflow.DOC_TRANSLATOR, Step.WORKFLOW_FAILED, "Failed", detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Workflow 4 — Lineage REST API (read-only, no timer)
# GET /api/lineage_summary?period=today|yesterday|last_7_days|last_30_days|overall
# ─────────────────────────────────────────────────────────────────────────────

@app.route(route="lineage_summary", methods=["GET"])
def lineage_summary(req: func.HttpRequest) -> func.HttpResponse:
    period       = req.params.get("period", "today").lower()
    country_code = req.params.get("countryCode")
    source_lang  = req.params.get("sourceLang")
    logger.info("lineage_summary | period=%s", period)

    try:
        result = get_lineage_summary_response(
            period=period,
            country_code=country_code,
            source_lang=source_lang,
        )
        return _json_ok(result)

    except ValueError as ve:
        logger.warning("lineage_summary bad input: %s", ve)
        return _err(str(ve), status_code=400)
    except Exception as exc:
        logger.error("lineage_summary error | %s", exc, exc_info=True)
        return _err(f"Error fetching lineage summary: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Workflow 4b — Attachment Lineage REST API (read-only, no timer)
# GET /api/attachment_lineage?period=today|yesterday|last_7_days|last_30_days|overall
#
# Returns one record per attachment with downloadable SAS links for:
#   original_file_link    — the raw uploaded file
#   translated_file_link  — the _en translated document
#   extracted_json_link   — the _en.json extraction output
# ─────────────────────────────────────────────────────────────────────────────

@app.route(route="attachment_lineage", methods=["GET"])
def attachment_lineage(req: func.HttpRequest) -> func.HttpResponse:
    period = req.params.get("period", "today").lower()
    logger.info("attachment_lineage | period=%s", period)

    try:
        result = get_attachment_lineage_response(period=period)
        return _json_ok(result)

    except ValueError as ve:
        logger.warning("attachment_lineage bad input: %s", ve)
        return _err(str(ve), status_code=400)
    except Exception as exc:
        logger.error("attachment_lineage error | %s", exc, exc_info=True)
        return _err(f"Error fetching attachment lineage: {exc}")
