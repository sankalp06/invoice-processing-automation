# Invoice Processing Platform

A production-grade monorepo with two independent workflows sharing common Azure infrastructure.

## Repository Structure

```
invoice_platform/
├── config/
│   └── settings.py                  ← Pydantic settings (all env vars, both workflows)
├── shared/                          ← Reusable clients and utilities
│   ├── clients/
│   │   ├── blob_client.py           ← Azure Blob Storage
│   │   ├── doc_intel_client.py      ← Azure Document Intelligence (OCR)
│   │   ├── translator_client.py     ← Azure Translator (text chunks)
│   │   ├── graph_client.py          ← Microsoft Graph (email)
│   │   └── llm_client.py            ← OpenAI-compatible LLM
│   ├── schemas/
│   │   ├── invoice_prompts.py       ← LLM system prompts
│   │   └── invoice_schemas.py       ← LLM function-call schemas
│   └── utils/
│       ├── blob_naming.py           ← Naming conventions + lang extraction
│       ├── logging.py               ← Structured logging setup
│       └── retry.py                 ← Exponential back-off decorator
├── workflows/
│   ├── doc_translator/              ← Workflow 1: Bulk container translation
│   │   ├── services/
│   │   │   ├── ocr_service.py
│   │   │   ├── translation_service.py
│   │   │   ├── extraction_service.py
│   │   │   └── pipeline_service.py
│   │   └── tests/
│   └── email_scanner/               ← Workflow 2: Email invoice scanning
│       ├── services/
│       │   ├── invoice_classifier.py    ← LLM: is this an invoice?
│       │   ├── language_detector.py     ← Translator detect API
│       │   ├── attachment_processor.py  ← Per-attachment pipeline
│       │   ├── email_composer.py        ← Vendor notification emails
│       │   └── email_scanner_pipeline.py ← Orchestrator
│       └── tests/
├── run_doc_translator.py            ← Entry point: Workflow 1
├── run_email_scanner.py             ← Entry point: Workflow 2
├── requirements.txt
└── .env.example
```

## Workflows

### Workflow 1 — Bulk Document Translator

Translates all PDFs in a source Azure container to English and stores them with extracted JSON.

```bash
python run_doc_translator.py                    # auto-detect language
python run_doc_translator.py --source-lang tr   # force Turkish source
python run_doc_translator.py --dry-run          # list blobs only
```

**Blob naming:** `invoice_tr.pdf` → `invoice_en.pdf` + `invoice_en.json`

---

### Workflow 2 — Email Invoice Scanner

Scans a mailbox inbox, validates attachments as invoices using OCR + LLM, stores them in the correct container, and replies to the vendor with a detailed notification.

```bash
python run_email_scanner.py                        # default lookback from .env
python run_email_scanner.py --lookback-hours 48    # scan last 48 hours
python run_email_scanner.py --dry-run              # list emails only
```

**Per-attachment flow:**
```
Download → OCR → Detect Language → Translate → LLM Classify
  ├── Valid invoice   → raw-invoices/<stem>_<langcode>.<ext>
  └── Invalid         → invalid-invoices/<filename>
```

**Email notifications (sent back to vendor):**
| Outcome | Action |
|---|---|
| All valid | Polite confirmation reply |
| Some invalid | Reply listing valid ones + rejection table with reasons |
| All invalid | Full rejection reply with reasons and resubmission checklist |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in your Azure + MS Graph credentials
```

## Required Azure Resources

| Resource | Used by |
|---|---|
| Azure Blob Storage | Both workflows |
| Azure Document Intelligence | Both workflows (OCR) |
| Azure Translator | Both workflows (text translation + language detection) |
| Azure OpenAI / LLM | Both workflows (extraction + classification) |
| Microsoft Graph API | Email Scanner only |

### Required Blob Containers

| Container | Setting | Purpose |
|---|---|---|
| `ocr-invoices` | `SOURCE_CONTAINER` | Doc Translator source |
| `translated-invoices` | `TARGET_CONTAINER` | Doc Translator output |
| `raw-invoices` | `RAW_INVOICE_CONTAINER` | Email Scanner valid invoices |
| `invalid-invoices` | `INVALID_INVOICE_CONTAINER` | Email Scanner rejections |

### MS Graph Permissions Required

- `Mail.Read` — read inbox messages
- `Mail.Send` — send reply notifications
- `Mail.ReadWrite` — (optional) mark messages as read
