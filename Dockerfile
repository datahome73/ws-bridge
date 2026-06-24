FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY entrypoint.py .
COPY shared/ shared/
COPY server/ server/
COPY clients/ clients/
COPY scripts/ scripts/
COPY config/ config/

EXPOSE 8765

CMD ["python3", "-u", "/app/entrypoint.py"]
