# Single image used by the bot, api and worker services (different commands).
# Based on the official Playwright image so Chromium + its system deps are present.
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install Python dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium

# Copy the application source.
COPY . .

# Drop privileges: the Playwright image ships a non-root "pwuser".
RUN mkdir -p /app/logs && chown -R pwuser:pwuser /app
USER pwuser

# Default command is overridden per-service in docker-compose.
CMD ["python", "-m", "app.bot"]
