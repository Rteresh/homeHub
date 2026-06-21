FROM python:3.12-slim-bookworm

# ffmpeg нужен для обложек видео (apps/files/video_poster.py)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p storage/logs storage/files staticfiles \
    && python manage.py collectstatic --noinput \
    && chmod +x docker/entrypoint-web.sh docker/entrypoint-bot.sh

ENV PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=homehub.settings

RUN useradd --create-home --uid 1000 homehub \
    && chown -R homehub:homehub /app

USER homehub

EXPOSE 8000

CMD ["gunicorn", "homehub.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
