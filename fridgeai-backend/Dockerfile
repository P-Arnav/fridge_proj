FROM python:3.11-slim

WORKDIR /app

# Install prod deps only (no torch/transformers — Gemini handles vision)
COPY requirements-prod.txt requirements-prod.txt
RUN pip install --no-cache-dir -r requirements-prod.txt

# Copy application code
COPY . .

ENV PORT=8080
EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
