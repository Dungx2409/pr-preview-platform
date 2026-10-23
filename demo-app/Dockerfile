# Stage 1: Build virtual environment
FROM python:3.10-slim AS builder

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Minimal runtime image
FROM python:3.10-slim AS runtime

# Create dedicated non-root user and group
# appuser: UID 10001, GID 10001
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -s /sbin/nologin -d /app appuser

WORKDIR /app

# Copy virtualenv from builder
COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv

# Copy application source code
COPY --chown=appuser:appuser src/ /app/

# Environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1" \
    PORT="8000"

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
