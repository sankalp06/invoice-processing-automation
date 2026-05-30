# Document Translator Pipeline

A production-grade, batch-capable pipeline that translates documents from an Azure Blob Storage source container to English and saves both the translated document and a structured JSON result to a target container.

## Architecture

```
doc_translator/
├── config/
│   └── settings.py          # Pydantic-based config loaded from env
├── src/
│   ├── clients/
│   │   ├── blob_client.py   # Azure Blob Storage interactions
│   │   ├── doc_intel_client.py  # Azure Document Intelligence (OCR)
│   │   ├── translator_client.py # Azure Translator (text + document)
│   │   └── llm_client.py    # OpenAI-compatible LLM client
│   ├── services/
│   │   ├── ocr_service.py       # OCR extraction logic
│   │   ├── translation_service.py  # Text chunking + translation
│   │   ├── extraction_service.py   # LLM-based structured extraction
│   │   └── pipeline_service.py     # Orchestrates the full per-file flow
│   ├── schemas/
│   │   ├── invoice_prompts.py   # System prompts
│   │   └── invoice_schemas.py   # LLM function-call schemas
│   └── utils/
│       ├── blob_naming.py   # File naming conventions
│       ├── logging.py       # Structured logging setup
│       └── retry.py         # Retry / back-off utilities
├── main.py                  # Entry point — batch processes the container
├── requirements.txt
└── .env.example
```

## Naming Convention

| Location        | Name                              |
|-----------------|-----------------------------------|
| Source container | `invoice.pdf`                    |
| Target container | `invoice_en.pdf` (translated doc)|
| Target container | `invoice_en.json` (extracted data)|

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in .env with your Azure credentials
```

## Usage

```bash
# Auto-detect source language (default)
python main.py

# Specify source language
python main.py --source-lang zh

# Limit concurrency (default: 5)
python main.py --concurrency 10

# Dry run — list blobs only, no processing
python main.py --dry-run
```

## Environment Variables

See `.env.example` for all required variables.
