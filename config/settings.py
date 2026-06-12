"""
config/settings.py
──────────────────
Single source of truth for all environment variables.
All properties are lowercase to match the existing workflow convention.

    from config.settings import settings
    print(settings.storage_account_name)
"""
from __future__ import annotations
import os


class _Settings:
    """Lazy-read env vars — always reflects current os.environ state."""

    def _get(self, key: str, default: str = "") -> str:
        return os.environ.get(key, default)

    # ── Azure Storage ──────────────────────────────────────────────────────
    @property
    def storage_account_name(self) -> str:
        return self._get("STORAGE_ACCOUNT_NAME")

    @property
    def storage_account_key(self) -> str:
        return self._get("STORAGE_ACCOUNT_KEY")

    @property
    def source_container(self) -> str:
        return self._get("SOURCE_CONTAINER", "raw-invoices")
    
    @property
    def source_container_translation(self) -> str:
        return self._get("SOURCE_CONTAINER_TRANSLATION", "ocr-invoices")

    @property
    def target_container(self) -> str:
        return self._get("TARGET_CONTAINER", "translated-invoices")

    @property
    def ocr_target_container(self) -> str:
        return self._get("TARGET_CONTAINER_OCR", "ocr-invoices")

    @property
    def ocr_failed_container(self) -> str:
        return self._get("FAILED_CONTAINER_OCR", "ocr-failed")

    @property
    def raw_invoice_container(self) -> str:
        return self._get("RAW_INVOICE_CONTAINER", "raw-invoices")

    @property
    def invalid_invoice_container(self) -> str:
        return self._get("INVALID_INVOICE_CONTAINER", "invalid-invoices")

    # ── Azure Document Intelligence ────────────────────────────────────────
    @property
    def doc_intelligence_endpoint(self) -> str:
        return self._get("DOC_INTELLIGENCE_ENDPOINT")

    @property
    def doc_intelligence_key(self) -> str:
        return self._get("DOC_INTELLIGENCE_KEY")

    @property
    def ocr_model(self) -> str:
        return self._get("OCR_MODEL", "prebuilt-invoice")

    # ── Azure Translator ───────────────────────────────────────────────────
    @property
    def translator_endpoint(self) -> str:
        return self._get(
            "TRANSLATOR_ENDPOINT",
            "https://api.cognitive.microsofttranslator.com/",
        )

    @property
    def translator_key(self) -> str:
        return self._get("TRANSLATOR_KEY")

    @property
    def translator_region(self) -> str:
        return self._get("TRANSLATOR_REGION", "eastus")

    # ── LLM ───────────────────────────────────────────────────────────────
    @property
    def llm_endpoint(self) -> str:
        return self._get("LLM_ENDPOINT")

    @property
    def llm_api_key(self) -> str:
        return self._get("LLM_API_KEY")

    @property
    def llm_deployment_name(self) -> str:
        return self._get("LLM_DEPLOYMENT_NAME")

    # ── Microsoft Graph ────────────────────────────────────────────────────
    @property
    def ms_graph_client_id(self) -> str:
        return self._get("MS_GRAPH_CLIENT_ID")

    @property
    def ms_graph_client_secret(self) -> str:
        return self._get("MS_GRAPH_CLIENT_SECRET")

    @property
    def ms_graph_tenant_id(self) -> str:
        return self._get("MS_GRAPH_TENANT_ID")

    @property
    def mailbox(self) -> str:
        return self._get("MAILBOX")

    # ── Azure SQL ──────────────────────────────────────────────────────────
    @property
    def sql_connection_string(self) -> str:
        raw = self._get("SQL_CONNECTION_STRING")
        if not raw:
            return ""
        # Auto-fix missing Driver= prefix (common copy-paste mistake)
        if not raw.strip().startswith("Driver="):
            raw = "Driver={ODBC Driver 18 for SQL Server};" + raw
        return raw

    # ── Pipeline tuning ────────────────────────────────────────────────────
    @property
    def pipeline_concurrency(self) -> int:
        return int(self._get("PIPELINE_CONCURRENCY", "5"))

    @property
    def sas_expiry_hours(self) -> int:
        return int(self._get("SAS_EXPIRY_HOURS", "24"))

    @property
    def translation_chunk_size(self) -> int:
        return int(self._get("TRANSLATION_CHUNK_SIZE", "9000"))

    @property
    def email_lookback_hours(self) -> float:
        return float(self._get("EMAIL_LOOKBACK_HOURS", "1"))

    @property
    def timer_lookback_hours(self) -> float:
        return float(self._get("TIMER_LOOKBACK_HOURS", "0.5"))


# Module-level singleton
settings = _Settings()
