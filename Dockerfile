FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps (supervisor for dual-process management)
RUN apt-get update && apt-get install -y supervisor && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY entrypoint.py .
COPY shared/ shared/
COPY server/ server/
COPY clients/ clients/
COPY scripts/ scripts/
COPY config/ config/
COPY docs/ docs/

# Copy supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/ws-bridge.conf

EXPOSE 8765 8766

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/ws-bridge.conf"]
