FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy English model for Presidio PII masker
RUN python -m spacy download en_core_web_sm

# Copy project files
COPY . .

# Expose port
EXPOSE 8000

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Run uvicorn server
CMD ["python", "-m", "uvicorn", "auth:app", "--host", "0.0.0.0", "--port", "8000"]
