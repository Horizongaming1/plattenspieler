FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        alsa-utils \
        ca-certificates \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

CMD ["python", "-m", "src.main"]


FROM debian:bookworm-slim AS icecast

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        gettext-base \
        icecast2 \
    && rm -rf /var/lib/apt/lists/*

COPY docker/icecast.xml.template /etc/icecast2/icecast.xml.template
COPY docker/icecast-entrypoint.sh /usr/local/bin/icecast-entrypoint.sh
RUN chmod +x /usr/local/bin/icecast-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/icecast-entrypoint.sh"]
