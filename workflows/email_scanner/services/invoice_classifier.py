"""
workflows/email_scanner/services/invoice_classifier.py
────────────────────────────────────────────────────────
Uses the LLM to decide whether a piece of text is an invoice or not,
and if it is, returns the reason. If not, returns why it was rejected.
"""
from __future__ import annotations

import json
import logging

from openai import OpenAI

from config.settings import settings
from shared.clients.llm_client import create_llm_client
from shared.utils.retry import retry

logger = logging.getLogger(__name__)

_CLASSIFIER_SCHEMA = [
    {
        "name": "classify_document",
        "description": (
            "Classify whether a document is a valid commercial invoice "
            "that should be processed for accounts payable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "is_invoice": {
                    "type": "boolean",
                    "description": (
                        "True if the document is a legitimate commercial invoice "
                        "(has invoice number, date, vendor, amount due). "
                        "False for receipts, statements, marketing material, "
                        "delivery notes, packing lists, or unrelated documents."
                    ),
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Confidence level of the classification.",
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Brief explanation of why the document is or is not classified "
                        "as an invoice. For rejections, be specific about what is missing "
                        "or wrong (e.g. 'Document is a delivery note, not an invoice — "
                        "no invoice number or amount payable found.')."
                    ),
                },
                "detected_vendor": {
                    "type": "string",
                    "description": "Vendor/supplier name if detectable, else empty string.",
                },
                "detected_invoice_number": {
                    "type": "string",
                    "description": "Invoice number if detectable, else empty string.",
                },
            },
            "required": ["is_invoice", "confidence", "reason"],
        },
    }
]

_SYSTEM_PROMPT = """
You are an accounts payable assistant. Your job is to review documents and determine 
whether they are valid commercial invoices that should be processed for payment.

A valid invoice MUST have:
- An invoice number (or reference number)
- An invoice date
- A vendor/supplier name or identifier
- A payable amount or line items with amounts

Documents that are NOT invoices: delivery notes, packing slips, purchase orders, 
statements of account, receipts for already-paid items, marketing brochures, 
contracts, legal documents, or any document without a clear amount owed.

Be strict but fair. When rejecting, clearly state what key elements are missing.
""".strip()


class InvoiceClassifier:
    def __init__(self, llm_client: OpenAI | None = None) -> None:
        self._llm = llm_client or create_llm_client()
        self._model = settings.llm_deployment_name

    @retry(max_attempts=3, base_delay=2.0, exceptions=(Exception,))
    def classify(self, text: str, filename: str) -> dict:
        """
        Classify whether *text* represents a valid invoice.

        Returns
        -------
        dict with keys:
            is_invoice (bool), confidence (str), reason (str),
            detected_vendor (str), detected_invoice_number (str)
        """
        logger.info("Classifying document: %s", filename)

        response = self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Filename: {filename}\n\n"
                        f"Document text (first 4000 chars):\n{text[:4000]}"
                    ),
                },
            ],
            functions=_CLASSIFIER_SCHEMA,
            function_call={"name": "classify_document"},
            max_tokens=500,
        )

        choice = response.choices[0]
        if not choice.message or not choice.message.function_call:
            logger.warning("LLM did not return a function call for %s", filename)
            return {
                "is_invoice": False,
                "confidence": "low",
                "reason": "Classification failed — LLM did not return a structured response.",
                "detected_vendor": "",
                "detected_invoice_number": "",
            }

        result = json.loads(choice.message.function_call.arguments)
        logger.info(
            "Classification for %s: is_invoice=%s confidence=%s",
            filename,
            result.get("is_invoice"),
            result.get("confidence"),
        )
        return result
