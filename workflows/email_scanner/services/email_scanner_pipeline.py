"""
workflows/email_scanner/services/email_scanner_pipeline.py
────────────────────────────────────────────────────────────
Orchestrates the full email scanning workflow:
  1. List inbox messages within lookback window
  2. For each message, list and filter attachments
  3. Process each attachment (OCR → translate → classify → store)
  4. Send appropriate notification email back to sender:
       - All valid   → success reply
       - Some invalid → partial failure reply
       - All invalid  → full failure reply
  5. Return a structured summary of all processing results
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from config.settings import settings
from shared.clients.blob_client import AzureBlobStorageClient
from shared.clients.doc_intel_client import AzureDocumentIntelligenceClient
from shared.clients.graph_client import MSGraphClient
from shared.clients.translator_client import AzureTranslatorClient
from workflows.email_scanner.services.attachment_processor import (
    AttachmentProcessor,
    AttachmentResult,
)
from workflows.email_scanner.services.email_composer import (
    AttachmentOutcome,
    compose_full_failure_email,
    compose_partial_failure_email,
    compose_success_email,
)
from workflows.email_scanner.services.invoice_classifier import InvoiceClassifier
from workflows.email_scanner.services.language_detector import LanguageDetector

logger = logging.getLogger(__name__)


@dataclass
class MessageResult:
    message_id: str
    subject: str
    sender_email: str
    sender_name: str
    attachment_results: list[AttachmentResult] = field(default_factory=list)
    notification_sent: bool = False
    error: str | None = None

    @property
    def valid_count(self) -> int:
        return sum(1 for r in self.attachment_results if r.is_valid)

    @property
    def invalid_count(self) -> int:
        return sum(1 for r in self.attachment_results if not r.is_valid)

    @property
    def all_valid(self) -> bool:
        return bool(self.attachment_results) and self.invalid_count == 0

    @property
    def all_invalid(self) -> bool:
        return bool(self.attachment_results) and self.valid_count == 0


@dataclass
class ScanResult:
    messages_scanned: int = 0
    messages_with_attachments: int = 0
    total_attachments: int = 0
    valid_invoices: int = 0
    invalid_invoices: int = 0
    message_results: list[MessageResult] = field(default_factory=list)


class EmailScannerPipeline:
    """End-to-end email scanning and invoice validation pipeline."""

    def __init__(
        self,
        graph_client: MSGraphClient,
        blob_client: AzureBlobStorageClient,
        doc_intel_client: AzureDocumentIntelligenceClient,
        translator_client: AzureTranslatorClient,
    ) -> None:
        self._graph = graph_client
        self._attachment_processor = AttachmentProcessor(
            blob_client=blob_client,
            doc_intel_client=doc_intel_client,
            translator_client=translator_client,
            classifier=InvoiceClassifier(),
            language_detector=LanguageDetector(),
        )

    # ── Public API ──────────────────────────────────────────────────────────

    def run(self, lookback_hours: int | None = None) -> ScanResult:
        """
        Scan the inbox and process all emails with attachments.

        Parameters
        ----------
        lookback_hours : How far back to scan (overrides settings default).
        """
        hours = lookback_hours or settings.email_lookback_hours
        logger.info("Email scanner starting — lookback=%dh", hours)

        messages = self._graph.list_messages(lookback_hours=hours)
        scan = ScanResult(messages_scanned=len(messages))

        for msg in messages:
            result = self._process_message(msg)
            if result:
                scan.message_results.append(result)
                scan.messages_with_attachments += 1
                scan.total_attachments += len(result.attachment_results)
                scan.valid_invoices += result.valid_count
                scan.invalid_invoices += result.invalid_count

        logger.info(
            "Scan complete — %d messages, %d attachments, %d valid, %d invalid",
            scan.messages_scanned,
            scan.total_attachments,
            scan.valid_invoices,
            scan.invalid_invoices,
        )
        return scan

    # ── Private ─────────────────────────────────────────────────────────────

    def _process_message(self, msg: dict) -> MessageResult | None:
        """Process one email message and send the appropriate notification."""
        message_id = msg["id"]
        subject = msg.get("subject", "(no subject)")
        sender = msg.get("from", {}).get("emailAddress", {})
        sender_email = sender.get("address", "")
        sender_name = sender.get("name", sender_email.split("@")[0])

        logger.info("Processing message from %s: %s", sender_email, subject)

        result = MessageResult(
            message_id=message_id,
            subject=subject,
            sender_email=sender_email,
            sender_name=sender_name,
        )

        try:
            attachments = self._graph.list_attachments(message_id)
            if not attachments:
                logger.info("No usable attachments in message %s — skipping", message_id)
                return None

            # Process attachments (sequentially per message to avoid rate-limiting Doc Intel)
            for att in attachments:
                att_id = att["id"]
                filename = att.get("name", f"attachment_{att_id}")
                raw_bytes = self._graph.download_attachment(message_id, att_id)
                att_result = self._attachment_processor.process(filename, raw_bytes)
                result.attachment_results.append(att_result)

            # Send notification back to sender
            self._send_notification(result)

        except Exception as exc:
            logger.exception("Failed to process message %s: %s", message_id, exc)
            result.error = str(exc)

        return result

    def _send_notification(self, result: MessageResult) -> None:
        """Compose and send the appropriate reply based on attachment outcomes."""
        outcomes = [
            AttachmentOutcome(
                filename=r.filename,
                is_valid=r.is_valid,
                reason=r.reason,
            )
            for r in result.attachment_results
        ]

        if result.all_valid:
            subject, body = compose_success_email(
                sender_name=result.sender_name,
                invoice_count=result.valid_count,
                original_subject=result.subject,
            )
        elif result.all_invalid:
            subject, body = compose_full_failure_email(
                sender_name=result.sender_name,
                outcomes=outcomes,
                original_subject=result.subject,
            )
        else:
            subject, body = compose_partial_failure_email(
                sender_name=result.sender_name,
                outcomes=outcomes,
                original_subject=result.subject,
            )

        try:
            self._graph.send_reply(message_id=result.message_id, body_html=body)
            result.notification_sent = True
            logger.info(
                "Notification sent to %s (%s/%s valid)",
                result.sender_email,
                result.valid_count,
                len(result.attachment_results),
            )
        except Exception as exc:
            logger.error(
                "Failed to send notification to %s: %s", result.sender_email, exc
            )
