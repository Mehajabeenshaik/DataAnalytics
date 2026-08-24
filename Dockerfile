FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy English model for Presidio PII masker
RUN python -m spacy download en_core_web_sm

# Copy project files
COPY . .

# Run as a non-root user (least privilege)
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/data /app/data/catalog /app/data/tenants \
    && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8001

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV PORT=8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -f http://localhost:8001/health || exit 1

# Run uvicorn server
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8001"]