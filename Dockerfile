FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 CLAIMVOICE_ENV=hosted PORT=8000
WORKDIR /service

COPY requirements-phone.txt .
RUN python -m pip install --no-cache-dir -r requirements-phone.txt \
    && groupadd --system claimvoice \
    && useradd --system --gid claimvoice --no-create-home claimvoice
COPY claimvoice ./claimvoice

USER claimvoice:claimvoice
EXPOSE 8000
CMD ["sh", "-c", "exec python -m uvicorn claimvoice.phone.telephony:app_factory --factory --host 0.0.0.0 --port \"$PORT\" --ws-max-size 16384 --ws-max-queue 8 --limit-concurrency 32 --timeout-graceful-shutdown 200 --no-access-log"]
