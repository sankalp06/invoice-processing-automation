"""
Tests for email composer — pure Python, no Azure/LLM calls needed.
"""
from workflows.email_scanner.services.email_composer import (
    AttachmentOutcome,
    compose_full_failure_email,
    compose_partial_failure_email,
    compose_success_email,
)


def test_success_email_contains_count():
    subject, body = compose_success_email("Acme Corp", 3, "Invoice Submission")
    assert "3" in body
    assert "RE: Invoice Submission" in subject
    assert "Acme Corp" in body


def test_full_failure_has_all_filenames():
    outcomes = [
        AttachmentOutcome("delivery_note.pdf", False, "This is a delivery note, not an invoice."),
        AttachmentOutcome("brochure.pdf", False, "Marketing brochure — no invoice number or amount."),
    ]
    subject, body = compose_full_failure_email("Vendor Ltd", outcomes, "Documents")
    assert "delivery_note.pdf" in body
    assert "brochure.pdf" in body
    assert "Action Required" in subject


def test_partial_failure_splits_correctly():
    outcomes = [
        AttachmentOutcome("invoice_001.pdf", True, "Valid invoice."),
        AttachmentOutcome("packing_list.pdf", False, "Packing list — no payable amount."),
    ]
    subject, body = compose_partial_failure_email("Supplier Inc", outcomes, "Monthly Docs")
    assert "invoice_001.pdf" in body
    assert "packing_list.pdf" in body
    assert "✅" in body
    assert "⚠️" in body


def test_success_subject_format():
    subject, _ = compose_success_email("Test", 1, "My Invoice")
    assert subject.startswith("RE: My Invoice")
