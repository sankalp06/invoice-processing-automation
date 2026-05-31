"""
shared/clients/graph_client.py
───────────────────────────────
Microsoft Graph API client.
Handles OAuth2 client-credentials token acquisition and all mailbox
operations: listing messages, downloading attachments, sending/replying.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Iterator

import requests

from config.settings import settings
from shared.utils.retry import retry

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Attachment MIME types we care about — everything else is skipped
SUPPORTED_ATTACHMENT_TYPES: set[str] = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/tiff",
    "image/tif",
}

# MIME types that are definitely noise (inline images, logos, footers)
SKIP_ATTACHMENT_TYPES: set[str] = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/bmp",
    "image/webp",
    "image/svg+xml",
}


class MSGraphClient:
    """Thin wrapper around Microsoft Graph for mailbox operations."""

    def __init__(self) -> None:
        self._client_id = settings.ms_graph_client_id
        self._client_secret = settings.ms_graph_client_secret
        self._tenant_id = settings.ms_graph_tenant_id
        self._mailbox = settings.mailbox
        self._token: str | None = None
        self._token_expiry: datetime = datetime.min.replace(tzinfo=UTC)

    # ── Auth ────────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        now = datetime.now(UTC)
        if self._token and now < self._token_expiry - timedelta(seconds=30):
            return self._token

        url = f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token"
        resp = requests.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = now + timedelta(seconds=int(data.get("expires_in", 3600)))
        logger.debug("MS Graph token refreshed, expires at %s", self._token_expiry)
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    # ── Message listing ─────────────────────────────────────────────────────

    @retry(max_attempts=3, base_delay=1.0, exceptions=(requests.HTTPError,))
    def list_messages(self, lookback_hours: int) -> list[dict]:
        """
        Return all inbox messages received within the last *lookback_hours*.
        Only messages that have at least one attachment are included.
        """
        since = (datetime.now(UTC) - timedelta(hours=lookback_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        url = (
            f"{_GRAPH_BASE}/users/{self._mailbox}/mailFolders/inbox/messages"
            f"?$filter=receivedDateTime ge {since} and hasAttachments eq true"
            f"&$select=id,subject,from,receivedDateTime,hasAttachments,conversationId"
            f"&$orderby=receivedDateTime desc"
            f"&$top=50"
        )
        messages: list[dict] = []
        while url:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            messages.extend(data.get("value", []))
            url = data.get("@odata.nextLink")  # handle pagination

        logger.info(
            "Found %d message(s) with attachments since %s", len(messages), since
        )
        return messages

    # ── Attachment handling ─────────────────────────────────────────────────

    @retry(max_attempts=3, base_delay=1.0, exceptions=(requests.HTTPError,))
    def list_attachments(self, message_id: str) -> list[dict]:
        """
        Return attachment metadata for *message_id*.
        Skips inline/image attachments automatically.
        """
        url = (
            f"{_GRAPH_BASE}/users/{self._mailbox}/messages/{message_id}/attachments"
            f"?$select=id,name,contentType,size,isInline"
        )
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        attachments = resp.json().get("value", [])

        filtered = []
        for att in attachments:
            content_type = (att.get("contentType") or "").lower().split(";")[0].strip()
            is_inline = att.get("isInline", False)
            size = att.get("size", 0)

            if is_inline:
                logger.debug("Skipping inline attachment: %s", att.get("name"))
                continue
            if content_type in SKIP_ATTACHMENT_TYPES:
                logger.debug(
                    "Skipping image attachment: %s (%s)", att.get("name"), content_type
                )
                continue
            if size < 100:  # skip suspiciously tiny files
                logger.debug(
                    "Skipping tiny attachment: %s (%d bytes)", att.get("name"), size
                )
                continue

            filtered.append(att)

        logger.info(
            "Message %s — %d usable attachment(s) of %d total",
            message_id,
            len(filtered),
            len(attachments),
        )
        return filtered

    @retry(max_attempts=3, base_delay=1.0, exceptions=(requests.HTTPError,))
    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Download attachment bytes (base64-decoded)."""
        import base64

        url = (
            f"{_GRAPH_BASE}/users/{self._mailbox}/messages/{message_id}"
            f"/attachments/{attachment_id}"
        )
        resp = requests.get(url, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        encoded = resp.json().get("contentBytes", "")
        return base64.b64decode(encoded)

    # ── Email sending ───────────────────────────────────────────────────────

    @retry(max_attempts=3, base_delay=2.0, exceptions=(requests.HTTPError,))
    def send_reply(self, message_id: str, body_html: str) -> None:
        """Send a reply to *message_id* with *body_html* as the body."""
        url = f"{_GRAPH_BASE}/users/{self._mailbox}/messages/{message_id}/reply"
        payload = {
            "message": {
                "body": {"contentType": "HTML", "content": body_html}
            },
            "comment": "",
        }
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=30)
        resp.raise_for_status()
        logger.info("Reply sent for message %s", message_id)

    @retry(max_attempts=3, base_delay=2.0, exceptions=(requests.HTTPError,))
    def send_new_email(self, to_address: str, subject: str, body_html: str) -> None:
        """Send a fresh email (not a reply)."""
        url = f"{_GRAPH_BASE}/users/{self._mailbox}/sendMail"
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": body_html},
                "toRecipients": [
                    {"emailAddress": {"address": to_address}}
                ],
            }
        }
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=30)
        resp.raise_for_status()
        logger.info("Email sent to %s: %s", to_address, subject)
