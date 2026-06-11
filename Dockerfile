FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ensure_sdk_media_protos.py scripts/ensure_sdk_media_protos.py
RUN python scripts/ensure_sdk_media_protos.py

COPY . .

EXPOSE 8000 50051

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
