FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PIP_NO_CACHE_DIR=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends libpq5 curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/docker-entrypoint.sh /app/docker.cloudflare.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]

EXPOSE 8000

FROM base AS development
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload"]


FROM development AS cloudflare
ENTRYPOINT ["/app/docker.cloudflare.sh"]
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload"]


FROM base AS production
RUN addgroup --system app && adduser --system --ingroup app app \
  && chown -R app:app /app
USER app
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "60"]
