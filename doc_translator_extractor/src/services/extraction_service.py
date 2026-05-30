"""
src/services/extraction_service.py
────────────────────────────────────
Uses the LLM client to extract structured invoice data from translated text.
"""

from __future__ import annotations

import json
import logging

from openai import OpenAI

from config.settings import settings
from src.clients.llm_client import create_llm_client
from src.schemas.invoice_prompts import BASELINE_SYSTEM_PROMPT, DETAILS_SYSTEM_PROMPT
from src.schemas.invoice_schemas import BASELINE_SCHEMA, DETAILS_SCHEMA
from src.utils.retry import retry

logger = logging.getLogger(__name__)


class ExtractionService:
    """Drives LLM-based structured extraction from translated invoice text."""

    def __init__(self, llm_client: OpenAI | None = None) -> None:
        self._llm = llm_client or create_llm_client()
        self._model = settings.llm_deployment_name

    def extract(self, translated_text: str) -> dict:
        """
        Run both extraction passes (baseline + details) and merge results.

        Parameters
        ----------
        translated_text : English text produced by the translation pipeline.

        Returns
        -------
        dict : Merged extraction result.
        """
        logger.info("Starting structured extraction")

        baseline = self._run_function_call(
            content=translated_text,
            system_prompt=BASELINE_SYSTEM_PROMPT,
            schema=BASELINE_SCHEMA,
        )
        details = self._run_function_call(
            content=translated_text,
            system_prompt=DETAILS_SYSTEM_PROMPT,
            schema=DETAILS_SCHEMA,
        )

        # Merge — details take precedence, baseline fills missing keys
        merged = {**baseline, **details}
        logger.info("Extraction complete — %d top-level fields", len(merged))
        return merged

    # ── Private ─────────────────────────────────────────────────────────────

    @retry(max_attempts=3, base_delay=2.0, exceptions=(Exception,))
    def _run_function_call(
        self,
        content: str,
        system_prompt: str,
        schema: list[dict],
    ) -> dict:
        """Call the LLM with a function schema and return the parsed result."""
        logger.debug("LLM function call: %s", schema[0]["name"])

        response = self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Extract invoice data from this text:\n{content}",
                },
            ],
            functions=schema,
            function_call="auto",
        )

        choice = response.choices[0]

        if (
            choice.finish_reason != "function_call"
            or not choice.message
            or not choice.message.function_call
        ):
            logger.warning(
                "LLM did not call a function (finish_reason=%s); returning empty dict",
                choice.finish_reason,
            )
            return {}

        return json.loads(choice.message.function_call.arguments)
