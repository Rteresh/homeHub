FROM python:3.12-slim-bookworm

# ffmpeg и pg_dump 16 для ops-панели (версия должна совпадать с postgres:16 в compose)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p storage/logs storage/files staticfiles \
    && python manage.py collectstatic --noinput \
    && chmod +x docker/entrypoint-web.sh docker/entrypoint-bot.sh scripts/*.sh

ENV PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=homehub.settings

RUN useradd --create-home --uid 1000 homehub \
    && chown -R homehub:homehub /app

USER homehub

EXPOSE 8000

CMD ["gunicorn", "homehub.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
