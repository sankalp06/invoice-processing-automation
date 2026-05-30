"""
src/schemas/invoice_schemas.py
───────────────────────────────
OpenAI function-call schemas for invoice data extraction.
Separated from prompts so each can evolve independently.
"""

from __future__ import annotations

BASELINE_SCHEMA: list[dict] = [
    {
        "name": "extract_invoice_baseline",
        "description": (
            "Extracts the invoice number and invoice date from raw invoice text. "
            "Only extract the actual invoice number, not PO numbers "
            "(PO numbers start with '66' or '45')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "invoiceNumber": {
                    "type": "string",
                    "description": (
                        "Unique invoice identifier. Must be taken from explicit invoice labels when present. "
                        "Ignore Customer Code, Vendor Number, Registration Number, "
                        "PO numbers starting with '66' or '45', page numbers."
                    ),
                },
                "invoiceDate": {
                    "type": "string",
                    "description": (
                        "Date the invoice was issued, Invoice/Billing/Issue date etc. "
                        "Normalize to YYYYMMDD."
                    ),
                },
            },
            "required": ["invoiceNumber", "invoiceDate"],
        },
    }
]

DETAILS_SCHEMA: list[dict] = [
    {
        "name": "extract_invoice_details",
        "description": (
            "Extracts structured invoice data including metadata, vendor/customer details, "
            "line items, totals, tax, tax percentage, and conditional fields based on invoice type. "
            "If a value cannot be reliably extracted, set it as an empty string (''). "
            "Do not use placeholder values such as 'N/A', 'unknown', 'not applicable', etc."
        ),
        "rules": {
            "POI": {
                "description": "PO Invoice",
                "criteria": [
                    "The document contains the keyword 'invoice'.",
                    "A valid PO number is present in the format '66' + 8 digits or '45' + 8 digits (e.g., '6600841982').",
                    "This classification applies ONLY if the document is NOT a Return type.",
                ],
            },
            "NPI": {
                "description": "Non-PO Invoice",
                "criteria": [
                    "The document contains the keyword 'invoice'.",
                    "No valid PO number is present.",
                    "If a vendor number is available, classify as NPI.",
                    "This classification applies ONLY if the document is NOT a Return type.",
                ],
            },
            "N/A": {
                "description": "Other AP Document",
                "criteria": ["The document does not meet any of the above criteria."],
            },
        },
        "parameters": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "Classified document type, derived based on rules defined under the 'rules' section.",
                    "enum": ["POI", "NPI"],
                },
                "invoiceType": {
                    "type": "string",
                    "description": (
                        "Type of invoice. Extract based on explicit keywords in the document. "
                        "If the document contains terms like 'Return', 'Credit Note', 'CN', 'Refund', "
                        "'Reversal', or Turkish keyword 'IADE', classify as 'RETURN'. "
                        "If the document title contains 'e-Serbest Meslek Makbuzu', classify as 'FREELANCE_INVOICE'. "
                        "If the document title contains 'Dekont', classify as 'RECEIPT'. "
                        "If the document title contains 'NOTERLÎK E-MAKBUZU', classify as 'NOTARY_E_RECEIPT'. "
                        "If the invoice is in a currency other than Turkish, classify as 'FOREIGN_CURRENCY'. "
                        "If the document relates to import transactions, classify as 'IMPORT'. "
                        "Otherwise, classify as 'STANDARD'. Do not infer unless clearly indicated."
                    ),
                    "enum": [
                        "STANDARD",
                        "RETURN",
                        "FOREIGN_CURRENCY",
                        "OUTSIDE_SCOPE",
                        "IMPORT",
                        "FREELANCE_INVOICE",
                        "RECEIPT",
                        "NOTARY_E_RECEIPT",
                    ],
                },
                "purchaseOrderNumber": {
                    "type": "string",
                    "description": (
                        "PO Number (required for POI only). "
                        "Must start with '66' or '45' followed by 8 digits (e.g., 4500841982)."
                    ),
                },
                "vendorNumber": {
                    "type": "string",
                    "description": "Vendor identifier (required for NPI only). May be labeled as Vendor ID, Vendor No., or Supplier ID.",
                },
                "taxAmount": {
                    "type": "number",
                    "description": "Total tax amount. May be negative for refunds or credit notes.",
                },
                "vatTaxAmount": {
                    "type": "number",
                    "description": "Total VAT tax amount. May be negative for refunds or credit notes.",
                },
                "totalNetAmount": {
                    "type": "number",
                    "description": "Total net amount of the transaction before tax.",
                },
                "totalInvoiceAmount": {
                    "type": "number",
                    "description": "Total invoice amount including tax. May be negative for credit notes.",
                },
                "taxIdentification": {
                    "type": "string",
                    "description": "Vendor's tax ID (e.g., VAT number, TIN).",
                },
                "receiverVATID": {"type": "string", "description": "Buyer's VAT ID."},
                "taxPercentage": {
                    "type": "number",
                    "description": "Overall tax percentage applied to the invoice (e.g., 10 for 10%).",
                },
                "vatPercentage": {
                    "type": "number",
                    "description": "Overall VAT percentage (e.g., 10 for 10%).",
                },
                "withholdingPercentage": {
                    "type": "number",
                    "description": "Withholding tax percentage. Extract ONLY if explicitly labeled.",
                },
                "Bank_Account_Number": {
                    "type": "string",
                    "description": "Bank account number (9–18 digits).",
                },
                "Global_Bank_Identifier": {
                    "type": "string",
                    "description": "SWIFT/BIC code (8 or 11 alphanumeric characters).",
                },
                "Bank_Key": {
                    "type": "string",
                    "description": "Bank routing/key code (format varies by country).",
                },
                "buyerName": {
                    "type": "string",
                    "description": "Buyer company name matched to predefined list.",
                    "enum": [
                        "GLAXOSMITHKLINE PHARMACEUTICALS INDUSTRY AND TRADE INC.",
                        "BIOVESTA PHARMACEUTICALS LIMITED COMPANY",
                        "GLAXOSMITHKLINE EXPORT LTD TURKEY LIAISON OFFICE",
                    ],
                },
                "currency": {
                    "type": "string",
                    "description": (
                        "ISO 4217 currency code (e.g., TRY, USD, EUR, JPY). "
                        "Determined only from valid monetary amounts. "
                        "If currency cannot be determined with high confidence, return an empty string."
                    ),
                },
                "invoiceLineItems": {
                    "type": "array",
                    "description": "List of invoice line items.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "lineNumber": {"type": "string"},
                            "description": {"type": "string"},
                            "category": {
                                "type": "string",
                                "description": "Classify the line item into one of the predefined categories.",
                                "enum": [
                                    "CONSTRUCTION_ENGINEERING",
                                    "CONSTRUCTION_CONSULTING",
                                    "CONSTRUCTION_INSPECTION",
                                    "CLEANING_FACILITY",
                                    "PERSONNEL_LABOR",
                                    "PERSONNEL_GENERAL",
                                    "PERSONNEL_TRANSPORT",
                                    "TRANSPORT_FREIGHT",
                                    "PROFESSIONAL_CATERING",
                                    "PROFESSIONAL_INTERMEDIARY",
                                    "ADVERTISING",
                                    "MAINTENANCE_TECHNICAL",
                                    "PRINTING_PUBLISHING",
                                    "MANUFACTURING_TEXTILE",
                                    "HEALTHCARE_PPP",
                                    "METALS_STANDARD",
                                    "METALS_SCRAP",
                                    "METALS_RECYCLED",
                                    "AGRI_RAW",
                                    "AGRI_FORESTRY",
                                    "INDUSTRIAL_IRON_STEEL",
                                    "INDUSTRIAL_OTHER_DELIVERIES",
                                    "OTHER_SERVICES",
                                ],
                            },
                            "quantity": {"type": "number"},
                            "unitOfMeasure": {"type": "string"},
                            "unitPrice": {"type": "number"},
                            "netAmount": {"type": "number"},
                            "taxAmount": {"type": "number"},
                            "taxPercentage": {"type": "number"},
                            "vatAmount": {"type": "number"},
                            "vatPercentage": {"type": "number"},
                            "withholdingPercentage": {"type": "number"},
                        },
                        "required": [
                            "lineNumber",
                            "category",
                            "quantity",
                            "unitOfMeasure",
                            "unitPrice",
                            "netAmount",
                            "vatAmount",
                            "vatPercentage",
                            "withholdingPercentage",
                        ],
                    },
                },
            },
            "required": [
                "doctype",
                "taxAmount",
                "vatTaxAmount",
                "totalInvoiceAmount",
                "invoiceLineItems",
                "taxPercentage",
                "vatPercentage",
                "currency",
            ],
        },
    }
]
