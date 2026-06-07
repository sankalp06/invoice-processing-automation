# =============================================================================
# Invoice Processing Platform — Azure Functions Container
# Base: Azure Functions Python 3.11
# =============================================================================
FROM mcr.microsoft.com/azure-functions/python:4-python3.11

# Azure Functions host config
ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    # Prevent ocrmypdf from trying to open a display
    DISPLAY="" \
    # Suppress PIL max image size warning for large invoice scans
    PYTHONWARNINGS="ignore"

# ── System dependencies (combined into one RUN to minimise layers) ────────────
RUN set -e && \
    # Temporarily add Debian Bookworm repo to get Ghostscript 10.x
    echo "deb http://deb.debian.org/debian bookworm main" > /etc/apt/sources.list.d/bookworm.list && \
    apt-get update && \
    apt-get install -y -t bookworm ghostscript && \
    rm -f /etc/apt/sources.list.d/bookworm.list && \
    \
    # Microsoft ODBC 18 for SQL Server (lineage DB)
    apt-get update && \
    apt-get install -y curl gnupg2 apt-transport-https && \
    curl https://packages.microsoft.com/keys/microsoft.asc \
        | tee /etc/apt/trusted.gpg.d/microsoft.asc && \
    curl https://packages.microsoft.com/config/debian/12/prod.list \
        | tee /etc/apt/sources.list.d/mssql-release.list && \
    # Strip signed-by directive if present (compatibility fix)
    sed -i 's/ signed-by=\/usr\/share\/keyrings\/microsoft-prod.gpg//' \
        /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc && \
    \
    # OCR + PDF + image libraries
    apt-get install -y \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-jpn \
        tesseract-ocr-tur \
        libtesseract-dev \
        libleptonica-dev \
        pkg-config \
        poppler-utils \
        libffi-dev \
        libjpeg-dev \
        zlib1g-dev \
        libpng-dev \
        # OpenCV runtime dependencies
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender-dev \
    && \
    # Cleanup
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# ── Application ───────────────────────────────────────────────────────────────
WORKDIR /home/site/wwwroot

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["/azure-functions-host/Microsoft.Azure.WebJobs.Script.WebHost"]
