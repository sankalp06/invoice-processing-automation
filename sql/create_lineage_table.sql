-- =============================================================================
-- Invoice Processing Platform — Lineage Tracking Table
-- =============================================================================
-- Run this once against your Azure SQL / SQL Server database.
-- Every workflow step writes one row; the lineage API aggregates across rows.
-- =============================================================================

CREATE TABLE invoice_process_log (

    -- ── Identity ──────────────────────────────────────────────────────────
    id               BIGINT          IDENTITY(1,1)   PRIMARY KEY,

    -- ── Run context ───────────────────────────────────────────────────────
    run_id           NVARCHAR(100)   NOT NULL,           -- e.g. "timer-workflow-20250530-123456-789"
    workflow_name    NVARCHAR(100)   NOT NULL,           -- e.g. "EmailScanner", "OCRPipeline"

    -- ── Step tracking ─────────────────────────────────────────────────────
    step_name        NVARCHAR(100)   NOT NULL,           -- e.g. "attachment_validated"
    step_value       NVARCHAR(500)   NULL,               -- filename, blob name, or any context string
    item_count       INT             NOT NULL DEFAULT 1, -- number of items this row represents

    -- ── Outcome ───────────────────────────────────────────────────────────
    -- Values used across the platform:
    --   email_received | attachment_processed | attachment_validation_passed
    --   attachment_validation_failed | ocr_completed | ocr_failed
    --   translation_completed | translation_failed
    --   extraction_completed | extraction_failed | workflow_completed | workflow_failed
    status           NVARCHAR(50)    NOT NULL,

    -- ── Timing ────────────────────────────────────────────────────────────
    logged_at        DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),

    -- ── Optional detail ───────────────────────────────────────────────────
    detail           NVARCHAR(MAX)   NULL,               -- error message, extra JSON, etc.

    -- ── Attachment file links ──────────────────────────────────────────────
    -- Populated for attachment-level steps; NULL for aggregate/workflow steps.
    filename              NVARCHAR(500)   NULL,          -- original attachment filename
    original_file_link    NVARCHAR(2000)  NULL,          -- SAS URL to original blob
    translated_file_link  NVARCHAR(2000)  NULL,          -- SAS URL to _en translated blob
    extracted_json_link   NVARCHAR(2000)  NULL           -- SAS URL to _en.json extraction
);

-- ── Indexes for lineage API queries ──────────────────────────────────────────
-- Lookups by date range (most common: "give me today's numbers")
CREATE NONCLUSTERED INDEX ix_ipl_logged_at
    ON invoice_process_log (logged_at DESC);

-- Lookups by workflow + step for aggregation
CREATE NONCLUSTERED INDEX ix_ipl_workflow_step
    ON invoice_process_log (workflow_name, step_name, logged_at DESC);

-- Lookups by run_id for drilling into a single run
CREATE NONCLUSTERED INDEX ix_ipl_run_id
    ON invoice_process_log (run_id, logged_at DESC);

-- ── Reference: step_name values and what they mean ───────────────────────────
--
-- EmailScanner workflow
--   email_received              One email with attachments landed in the mailbox
--   attachment_processed        Attachment downloaded and sent for processing
--   attachment_validation_passed  LLM classified attachment as a valid invoice
--   attachment_validation_failed  LLM rejected the attachment (not an invoice)
--
-- OCRPipeline workflow
--   ocr_completed               PDF successfully OCR'd and uploaded to target
--   ocr_failed                  PDF OCR failed even after image enhancement
--
-- DocTranslator workflow
--   translation_completed       Document translated and _en blob uploaded
--   translation_failed          Translation step failed for a document
--   extraction_completed        LLM extraction JSON uploaded successfully
--   extraction_failed           LLM extraction failed for a document
--
-- Any workflow
--   workflow_completed          Entire workflow run finished without critical error
--   workflow_failed             Entire workflow run aborted with a critical error
-- =============================================================================

-- =============================================================================
-- Migration: add attachment file-link columns
-- Run once on existing databases that were created before this migration.
-- =============================================================================
ALTER TABLE invoice_process_log
ADD
    filename              NVARCHAR(500)   NULL,
    original_file_link    NVARCHAR(2000)  NULL,
    translated_file_link  NVARCHAR(2000)  NULL,
    extracted_json_link   NVARCHAR(2000)  NULL;
-- =============================================================================
