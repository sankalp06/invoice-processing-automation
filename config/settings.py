"""
config/settings.py
──────────────────
Single source of truth for all configuration across every workflow.
"""
from __future__ import annotations
import os
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env" if os.path.exists(".env") else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Azure Storage ──────────────────────────────────────────────────────
    storage_account_name: str = Field(..., alias="STORAGE_ACCOUNT_NAME")
    storage_account_key: str = Field(..., alias="STORAGE_ACCOUNT_KEY")
    source_container: str = Field(..., alias="SOURCE_CONTAINER")
    target_container: str = Field(..., alias="TARGET_CONTAINER")
    raw_invoice_container: str = Field(..., alias="RAW_INVOICE_CONTAINER")
    invalid_invoice_container: str = Field(..., alias="INVALID_INVOICE_CONTAINER")

    # ── Azure Document Intelligence ────────────────────────────────────────
    doc_intelligence_endpoint: str = Field(..., alias="DOC_INTELLIGENCE_ENDPOINT")
    doc_intelligence_key: str = Field(..., alias="DOC_INTELLIGENCE_KEY")

    # ── Azure Translator ───────────────────────────────────────────────────
    translator_endpoint: str = Field(..., alias="TRANSLATOR_ENDPOINT")
    translator_key: str = Field(..., alias="TRANSLATOR_KEY")
    translator_region: str = Field(..., alias="TRANSLATOR_REGION")

    # ── LLM ───────────────────────────────────────────────────────────────
    llm_endpoint: str = Field(..., alias="LLM_ENDPOINT")
    llm_api_key: str = Field(..., alias="LLM_API_KEY")
    llm_deployment_name: str = Field(..., alias="LLM_DEPLOYMENT_NAME")

    # ── Microsoft Graph / Email Scanner ───────────────────────────────────
    ms_graph_client_id: str = Field(..., alias="MS_GRAPH_CLIENT_ID")
    ms_graph_client_secret: str = Field(..., alias="MS_GRAPH_CLIENT_SECRET")
    ms_graph_tenant_id: str = Field(..., alias="MS_GRAPH_TENANT_ID")
    mailbox: str = Field(..., alias="MAILBOX")

    # ── Pipeline Tuning ────────────────────────────────────────────────────
    pipeline_concurrency: int = Field(5, alias="PIPELINE_CONCURRENCY")
    sas_expiry_hours: int = Field(24, alias="SAS_EXPIRY_HOURS")
    translation_chunk_size: int = Field(9000, alias="TRANSLATION_CHUNK_SIZE")
    ocr_model: str = Field("prebuilt-invoice", alias="OCR_MODEL")
    email_lookback_hours: int = Field(24, alias="EMAIL_LOOKBACK_HOURS")

    @field_validator("pipeline_concurrency")
    @classmethod
    def concurrency_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("PIPELINE_CONCURRENCY must be >= 1")
        return v

    @field_validator("translation_chunk_size")
    @classmethod
    def chunk_within_api_limit(cls, v: int) -> int:
        if not (1 <= v <= 10_000):
            raise ValueError("TRANSLATION_CHUNK_SIZE must be between 1 and 10 000")
        return v


settings = Settings()  # type: ignore[call-arg]
