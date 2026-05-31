"""
workflows/email_scanner/services/email_composer.py
────────────────────────────────────────────────────
Generates polished, vendor-facing HTML email bodies for:
  - Full success  : all attachments were valid invoices
  - Partial failure: some attachments were valid, some were not
  - Full failure  : no attachments were valid invoices

All emails are written from the perspective of the customer's AP team,
addressed respectfully to the vendor/supplier.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class AttachmentOutcome:
    filename: str
    is_valid: bool
    reason: str  # rejection reason if not valid


def _now_str() -> str:
    return datetime.now(UTC).strftime("%d %B %Y")


def _html_wrap(body: str) -> str:
    return f"""
<html><body style="font-family: Arial, sans-serif; font-size: 14px; color: #222; line-height: 1.6;">
{body}
<br/>
<p style="color:#555; font-size:12px;">
  This is an automated notification from the Accounts Payable processing system.<br/>
  Please do not reply directly to this message — use the contact details below for queries.
</p>
</body></html>
""".strip()


def compose_success_email(
    sender_name: str,
    invoice_count: int,
    original_subject: str,
) -> tuple[str, str]:
    """
    Returns (subject, html_body) for a full-success notification.
    """
    subject = f"RE: {original_subject} — Invoice(s) Received Successfully"
    body = _html_wrap(f"""
<p>Dear {sender_name},</p>

<p>Thank you for submitting your invoice(s). We are pleased to confirm that we have
successfully received and processed all <strong>{invoice_count}</strong> attachment(s)
from your email dated <strong>{_now_str()}</strong>.</p>

<p>Your invoice(s) have been registered in our Accounts Payable system and will be
reviewed in accordance with our standard payment terms. You can expect payment
to be processed within the agreed timeline.</p>

<p>If you have any questions regarding the status of your payment, please do not
hesitate to contact our AP team.</p>

<p>We appreciate your continued partnership.</p>

<p>Kind regards,<br/>
<strong>Accounts Payable Team</strong></p>
""")
    return subject, body


def compose_partial_failure_email(
    sender_name: str,
    outcomes: list[AttachmentOutcome],
    original_subject: str,
) -> tuple[str, str]:
    """
    Returns (subject, html_body) for a mixed result — some valid, some not.
    """
    valid = [o for o in outcomes if o.is_valid]
    invalid = [o for o in outcomes if not o.is_valid]

    subject = f"RE: {original_subject} — Action Required: Some Attachments Could Not Be Processed"

    invalid_rows = "".join(
        f"""<tr>
          <td style="padding:6px 12px; border:1px solid #ddd;">{o.filename}</td>
          <td style="padding:6px 12px; border:1px solid #ddd; color:#c0392b;">{o.reason}</td>
        </tr>"""
        for o in invalid
    )

    valid_list = "".join(f"<li>{o.filename}</li>" for o in valid)

    body = _html_wrap(f"""
<p>Dear {sender_name},</p>

<p>Thank you for sending your invoice(s). We have reviewed all attachments from
your email dated <strong>{_now_str()}</strong> and wish to inform you of the following:</p>

<p><strong>✅ Successfully Processed ({len(valid)} attachment(s)):</strong></p>
<ul>{valid_list}</ul>

<p>The above invoices have been registered in our Accounts Payable system and will
proceed through our normal payment process.</p>

<p><strong>⚠️ Attachments Requiring Your Attention ({len(invalid)}):</strong></p>

<p>Unfortunately, the following attachment(s) could not be accepted as valid invoices.
Please review the reason(s) listed below and resubmit the corrected document(s) at
your earliest convenience:</p>

<table style="border-collapse:collapse; width:100%; margin-top:8px;">
  <thead>
    <tr style="background:#f2f2f2;">
      <th style="padding:8px 12px; border:1px solid #ddd; text-align:left;">Attachment</th>
      <th style="padding:8px 12px; border:1px solid #ddd; text-align:left;">Reason</th>
    </tr>
  </thead>
  <tbody>{invalid_rows}</tbody>
</table>

<p style="margin-top:16px;">Please ensure that each resubmitted invoice clearly
includes the invoice number, invoice date, your company name, a description of
goods or services, and the total amount payable. This will help us process your
documents without further delays.</p>

<p>We apologise for any inconvenience and thank you for your understanding and
prompt cooperation.</p>

<p>Kind regards,<br/>
<strong>Accounts Payable Team</strong></p>
""")
    return subject, body


def compose_full_failure_email(
    sender_name: str,
    outcomes: list[AttachmentOutcome],
    original_subject: str,
) -> tuple[str, str]:
    """
    Returns (subject, html_body) when all attachments are invalid.
    """
    subject = f"RE: {original_subject} — Action Required: Invoice(s) Could Not Be Processed"

    rows = "".join(
        f"""<tr>
          <td style="padding:6px 12px; border:1px solid #ddd;">{o.filename}</td>
          <td style="padding:6px 12px; border:1px solid #ddd; color:#c0392b;">{o.reason}</td>
        </tr>"""
        for o in outcomes
    )

    body = _html_wrap(f"""
<p>Dear {sender_name},</p>

<p>Thank you for reaching out to our Accounts Payable department. We have carefully
reviewed all attachment(s) included in your email dated <strong>{_now_str()}</strong>;
however, we regret to inform you that none of the documents could be accepted for
processing as a valid invoice.</p>

<p>Please find the details below:</p>

<table style="border-collapse:collapse; width:100%; margin-top:8px;">
  <thead>
    <tr style="background:#f2f2f2;">
      <th style="padding:8px 12px; border:1px solid #ddd; text-align:left;">Attachment</th>
      <th style="padding:8px 12px; border:1px solid #ddd; text-align:left;">Reason for Rejection</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>

<p style="margin-top:16px;">To ensure your invoice is processed promptly, please
resubmit your document(s) making sure each invoice includes:</p>

<ul>
  <li>A unique invoice number</li>
  <li>Invoice date</li>
  <li>Your company name and contact details</li>
  <li>A clear description of goods or services provided</li>
  <li>The total amount payable (including any applicable taxes)</li>
</ul>

<p>We understand this may cause inconvenience and sincerely apologise for any
disruption. Our team is happy to assist if you have questions about our invoicing
requirements — please contact us at your earliest convenience.</p>

<p>We look forward to receiving your corrected submission.</p>

<p>Kind regards,<br/>
<strong>Accounts Payable Team</strong></p>
""")
    return subject, body
