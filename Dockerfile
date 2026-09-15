FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install dependencies (skipping heavy torch if not needed in runtime loop)
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/logs /app/data

EXPOSE 8501

CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]
