"""
loggers/log_db.py
──────────────────
Single module responsible for writing to and reading from invoice_process_log.

All workflows call log_step() to record progress.
The lineage REST API calls get_lineage_summary() to aggregate results.

Uses pyodbc + the SQL_CONNECTION_STRING from config/settings.py.
Connection pooling is handled at the Azure Functions host level; each call
opens and closes its own connection to stay stateless.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

import pyodbc

from config.settings import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Step name constants — import these in workflows instead of raw strings
# ─────────────────────────────────────────────────────────────────────────────
class Step:
    EMAIL_RECEIVED                  = "email_received"
    ATTACHMENT_PROCESSED            = "attachment_processed"
    ATTACHMENT_VALIDATION_PASSED    = "attachment_validation_passed"
    ATTACHMENT_VALIDATION_FAILED    = "attachment_validation_failed"
    OCR_COMPLETED                   = "ocr_completed"
    OCR_FAILED                      = "ocr_failed"
    TRANSLATION_COMPLETED           = "translation_completed"
    TRANSLATION_FAILED              = "translation_failed"
    EXTRACTION_COMPLETED            = "extraction_completed"
    EXTRACTION_FAILED               = "extraction_failed"
    WORKFLOW_COMPLETED              = "workflow_completed"
    WORKFLOW_FAILED                 = "workflow_failed"


class Workflow:
    EMAIL_SCANNER       = "EmailScanner"
    OCR_PIPELINE        = "OCRPipeline"
    DOC_TRANSLATOR      = "DocTranslator"
    SFTP_UPLOAD         = "SFTPUpload"
    DAILY_REPORT        = "DailyReport"


# ─────────────────────────────────────────────────────────────────────────────
# Connection helper
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def _get_conn() -> Generator[pyodbc.Connection, None, None]:
    conn = pyodbc.connect(settings.sql_connection_string, timeout=10)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────────────────────

def log_step(
    run_id: str,
    workflow_name: str,
    step_name: str,
    status: str,
    step_value: str | None = None,
    item_count: int = 1,
    detail: str | None = None,
    logged_at: datetime | None = None,
) -> None:
    """
    Insert one row into invoice_process_log.

    Parameters
    ----------
    run_id        : Unique identifier for the workflow run.
    workflow_name : Use Workflow.* constants.
    step_name     : Use Step.* constants.
    status        : Free text — "Completed", "Failed", "InProgress", etc.
    step_value    : Optional blob name, filename, or other item identifier.
    item_count    : Number of items this row represents (default 1).
    detail        : Optional extra context / error message.
    logged_at     : Override timestamp (defaults to UTC now).
    """
    if not settings.sql_connection_string:
        logger.debug(
            "SQL_CONNECTION_STRING not set — skipping lineage log: %s / %s",
            workflow_name, step_name,
        )
        return

    ts = logged_at or datetime.now(timezone.utc)
    sql = """
        INSERT INTO invoice_process_log
            (run_id, workflow_name, step_name, step_value, item_count, status, logged_at, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        with _get_conn() as conn:
            conn.execute(sql, (run_id, workflow_name, step_name, step_value, item_count, status, ts, detail))
        logger.debug("Logged step: %s / %s / %s", run_id, step_name, status)
    except Exception as exc:
        # Never let a lineage write crash the main workflow
        logger.error("Failed to write lineage log: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Read — lineage summary aggregation
# ─────────────────────────────────────────────────────────────────────────────

def _date_filter(period: str) -> str:
    """Return a SQL WHERE clause fragment for the given period."""
    filters = {
        "today":        "CAST(logged_at AS DATE) = CAST(GETUTCDATE() AS DATE)",
        "yesterday":    "CAST(logged_at AS DATE) = CAST(DATEADD(DAY, -1, GETUTCDATE()) AS DATE)",
        "last_7_days":  "logged_at >= DATEADD(DAY, -7, GETUTCDATE())",
        "last_30_days": "logged_at >= DATEADD(DAY, -30, GETUTCDATE())",
        "overall":      "1=1",
    }
    if period not in filters:
        raise ValueError(f"Invalid period '{period}'. Choose from: {list(filters)}")
    return filters[period]


def get_lineage_summary(period: str = "today") -> dict:
    """
    Return aggregated pipeline metrics for the given period.

    Returns
    -------
    dict with keys matching the lineage API contract:
        emails_received, attachments_processed,
        attachment_validation_passed, attachment_validation_failed,
        ocr_completed, ocr_failed,
        translation_completed, translation_failed,
        extraction_completed, extraction_failed,
        workflow_completed, workflow_failed
    """
    where = _date_filter(period)

    sql = f"""
        SELECT
            step_name,
            SUM(item_count) AS total
        FROM invoice_process_log
        WHERE {where}
        GROUP BY step_name
    """

    counts: dict[str, int] = {}
    try:
        with _get_conn() as conn:
            rows = conn.execute(sql).fetchall()
        for row in rows:
            counts[row[0]] = row[1]
    except Exception as exc:
        logger.error("Failed to read lineage summary: %s", exc)
        raise

    return {
        "period":                       period,
        "emails_received":              counts.get(Step.EMAIL_RECEIVED, 0),
        "attachments_processed":        counts.get(Step.ATTACHMENT_PROCESSED, 0),
        "attachment_validation_passed": counts.get(Step.ATTACHMENT_VALIDATION_PASSED, 0),
        "attachment_validation_failed": counts.get(Step.ATTACHMENT_VALIDATION_FAILED, 0),
        "ocr_completed":                counts.get(Step.OCR_COMPLETED, 0),
        "ocr_failed":                   counts.get(Step.OCR_FAILED, 0),
        "translation_completed":        counts.get(Step.TRANSLATION_COMPLETED, 0),
        "translation_failed":           counts.get(Step.TRANSLATION_FAILED, 0),
        "extraction_completed":         counts.get(Step.EXTRACTION_COMPLETED, 0),
        "extraction_failed":            counts.get(Step.EXTRACTION_FAILED, 0),
        "workflow_completed":           counts.get(Step.WORKFLOW_COMPLETED, 0),
        "workflow_failed":              counts.get(Step.WORKFLOW_FAILED, 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Legacy shim — keeps any existing callers of invoice_process_step() working
# ─────────────────────────────────────────────────────────────────────────────

def invoice_process_step(
    run_id: str,
    workflow_name: str,
    step_name: str,
    item_count: int,
    status: str,
    logged_at: datetime,
    detail: str | None = None,
) -> None:
    """Backward-compatible wrapper around log_step()."""
    log_step(
        run_id=run_id,
        workflow_name=workflow_name,
        step_name=step_name,
        status=status,
        item_count=item_count,
        detail=detail,
        logged_at=logged_at,
    )
