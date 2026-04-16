FROM python:3.11-slim

WORKDIR /app

# Install server dependencies only (no playwright/scrapers)
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Copy application
COPY server.py .
COPY ai_agent/ ./ai_agent/
COPY docs/ ./docs/

# Cloud Run sets PORT env var — server.py reads it
ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
