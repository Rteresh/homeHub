# HomeHub

HomeHub — локальный домашний сервер на Django для приватного хранения файлов и медиатеки. Проект принимает фото, видео, GIF и документы через сайт и Telegram-бота, хранит файлы в локальном приватном storage и показывает медиатеку с просмотрщиком.

## Возможности

- Веб-интерфейс Django.
- Авторизация на сайте через одноразовую ссылку из Telegram.
- Telegram-бот на aiogram.
- Приём фото, видео, GIF и документов из Telegram.
- Альбомы: группировка файлов через меню «Альбом» в боте и раздел «Альбомы» на сайте.
- Приватное локальное хранилище файлов.
- Медиатека с сортировкой по дате: новые файлы сверху.
- Обложки видео (первый кадр) для плиток медиатеки и альбомов.
- Просмотрщик фото и видео с навигацией между медиафайлами.
- PostgreSQL как рабочая база данных.
- Скрипты единого запуска и остановки сайта вместе с ботом.

## Требования

- Python 3.12 или новее.
- PostgreSQL.
- `ffmpeg` для генерации обложек видео (macOS: `brew install ffmpeg`).
- Telegram bot token от BotFather.
- macOS/Linux shell для скриптов `start_homehub.sh` и `stop_homehub.sh`.

## Структура

```text
homeHub/
  apps/
    accounts/      # Telegram-профили, быстрый вход через Telegram
    files/         # файлы, медиатека, preview/download, загрузка
    web/           # главные страницы и общий web UI
  bot/             # Telegram-бот aiogram
  homehub/         # настройки и URL Django-проекта
  storage/         # приватные файлы и логи, не хранится в git
  .env             # локальные настройки и секреты
  start_homehub.sh # запуск сайта и бота
  stop_homehub.sh  # остановка сайта и бота
```

## Быстрая установка

1. Перейти в папку проекта:

2. Создать и активировать виртуальное окружение:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

3. Установить зависимости:

```bash
pip install -r requirements.txt
```

Для разработки с pytest:

```bash
pip install -r requirements-dev.txt
```

4. Подготовить PostgreSQL.

Если PostgreSQL установлен через Homebrew:

```bash
brew services start postgresql@16
```

Создать пользователя и базу, если их ещё нет:

```bash
createuser homehub
createdb homehub -O homehub
```

Если у пользователя PostgreSQL нужен пароль, задайте его в `psql` и укажите такой же в `.env`:

```sql
ALTER USER homehub WITH PASSWORD 'homehub';
```

5. Настроить `.env`.

Можно взять шаблон:

```bash
cp .env.example .env
```


`TELEGRAM_BOT_TOKEN` должен быть настоящим токеном вашего бота. Не публикуйте `.env` и не отправляйте токен в чатах.

1. Применить миграции:

```bash
.venv/bin/python manage.py migrate
```

Миграции сразу создают два разрешённых Telegram-профиля:

 — администратор бота и staff-пользователь Django.
 — обычный разрешённый пользователь.

1. Проверить проект:

```bash
.venv/bin/python manage.py check
```

## Запуск

Запуск сайта и Telegram-бота одной командой:

```bash
./start_homehub.sh
```

Скрипт делает следующее:

- читает `.env`;
- применяет миграции;
- запускает Django-сайт на `SITE_HOST:SITE_PORT`;
- запускает Telegram-бота;
- пишет PID-файлы в `.run/`;
- пишет логи в `storage/logs/`.

После запуска сайт будет доступен по адресу:

```text
http://127.0.0.1:8001
```

Медиатека:

```text
http://127.0.0.1:8001/media/
```

## Остановка

Остановить сайт и Telegram-бота:

```bash
./stop_homehub.sh
```

Скрипт останавливает процессы из `.run/*.pid` и дополнительно убирает найденные процессы HomeHub, если PID-файл устарел.

## Как войти на сайт через Telegram

1. Запустите проект:

```bash
./start_homehub.sh
```

2. Откройте своего Telegram-бота.

3. Отправьте команду:

```text
/login
```

4. Бот отправит одноразовую ссылку входа. Ссылка действует 10 минут.

5. Откройте ссылку в браузере. После входа сайт переведёт вас в медиатеку.

Если бот отвечает, что доступ закрыт, проверьте, что ваш Telegram ID есть в базе и указан в разрешённых пользователях.

## Как отправлять данные через Telegram

Бот принимает:

- фото;
- видео;
- GIF-анимации;
- документы.

Отправьте файл прямо в чат с ботом. Бот скачает файл, сохранит его в приватное хранилище и создаст запись `FileAsset`.

**Лимит Telegram Bot API:** в стандартном режиме бот может скачать файлы до **20 МБ**. Большие файлы загружайте через сайт `/files/upload/`. Для приёма файлов до ~2 ГБ из Telegram см. раздел ниже.

Команды бота:

```text
/start
/help
/login
/media
/dictionary
```

`/media` показывает последние сохранённые медиафайлы пользователя.

### Альбомы в боте

Кнопка **«Альбом»** открывает подменю:

- **Без альбома** — новые файлы сохраняются без привязки к альбому;
- **Выбрать альбом** — inline-список существующих альбомов;
- **Создать альбом** — введите название; альбом станет активным для следующих загрузок.

Пока выбран активный альбом, все файлы из Telegram попадают в него. На сайте альбомы доступны в разделе `/albums/`, при загрузке через `/files/upload/` можно выбрать альбом из списка.

### Обложки видео

Для плиток медиатеки и альбомов HomeHub создаёт JPEG-обложку из первого кадра видео через `ffmpeg`. Для уже загруженных видео без обложки:

```bash
python manage.py generate_video_posters
```

## Большие файлы из Telegram (больше 20 МБ)

Стандартный Telegram Bot API не отдаёт боту файлы крупнее 20 МБ. Это ограничение Telegram, а не HomeHub.

Варианты:

1. Загрузить файл через сайт: `/files/upload/`
2. Подключить **Local Bot API Server** — тогда бот сможет принимать файлы до ~2 ГБ

### Local Bot API (опционально)

1. Получите `api_id` и `api_hash` на [my.telegram.org](https://my.telegram.org).
2. Запустите локальный сервер (пример через Docker):

```bash
docker run -d --name telegram-bot-api \
  -p 8081:8081 \
  -v telegram-bot-api-data:/var/lib/telegram-bot-api \
  -e TELEGRAM_API_ID=YOUR_API_ID \
  -e TELEGRAM_API_HASH=YOUR_API_HASH \
  aiogram/telegram-bot-api:latest \
  --local --http-port=8081 --dir=/var/lib/telegram-bot-api
```

3. Добавьте в `.env`:

```env
TELEGRAM_API_BASE_URL=http://127.0.0.1:8081
TELEGRAM_LOCAL_MODE=true
TELEGRAM_LOCAL_FILES_PATH=/var/lib/telegram-bot-api
TELEGRAM_DOWNLOAD_TIMEOUT=600
```

4. Перезапустите HomeHub: `./stop_homehub.sh && ./start_homehub.sh`

Если `TELEGRAM_API_BASE_URL` пустой, бот работает через `api.telegram.org` с лимитом 20 МБ.

## Веб-разделы

- `/files/` — общий список файлов, фильтры, скачивание и удаление.
- `/files/upload/` — загрузка файла через сайт.
- `/media/` — медиатека фото, видео и GIF.
- `/media/<uuid>/` — просмотрщик конкретного медиафайла.
- `/admin/` — Django admin.

## Логи и PID-файлы

### Веб-интерфейс (staff)

Пользователи с флагом **staff** видят пункты «Журналы» и «Скрипты» в меню:

- `/ops/logs/` — tail журналов из `storage/logs/`
- `/ops/scripts/` — запуск whitelisted-скриптов backup/export

### Файлы

Логи:

```text
storage/logs/web.log
storage/logs/bot.log
storage/logs/gunicorn-access.log   # Docker + gunicorn
storage/logs/gunicorn-error.log
storage/logs/backup.log            # скрипты backup/export
```

На сервере: `/srv/storage/homehub/logs/`.

### Docker

```bash
docker compose logs -f web
docker compose logs -f bot
```

PID-файлы:

```text
.run/web.pid
.run/bot.pid
```

`storage/` и `.run/` не должны попадать в git.

## Полезные команды

Проверить настройки Django:

```bash
.venv/bin/python manage.py check
```

Проверить, нужны ли новые миграции:

```bash
.venv/bin/python manage.py makemigrations --check --dry-run
```

Создать суперпользователя Django:

```bash
.venv/bin/python manage.py createsuperuser
```

Запустить только сайт вручную:

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8001 --noreload
```

Запустить только Telegram-бота вручную:

```bash
.venv/bin/python -m bot.main
```

## Частые проблемы

### `RuntimeError: TELEGRAM_BOT_TOKEN не задан в окружении`

Проверьте, что:

- файл `.env` лежит в корне проекта;
- в `.env` заполнен `TELEGRAM_BOT_TOKEN`;
- команда запуска выполняется из папки проекта или через `./start_homehub.sh`.

### Не подключается PostgreSQL

Проверьте, что PostgreSQL запущен:

```bash
brew services list
```

Проверьте доступ к базе:

```bash
psql -h 127.0.0.1 -U homehub -d homehub
```

Если пароль отличается, обновите `POSTGRES_PASSWORD` в `.env`.

### Сайт не открывается

Проверьте лог:

```bash
tail -100 storage/logs/web.log
```

Проверьте, что порт совпадает с `SITE_PORT` в `.env`.

### Бот не отвечает

Проверьте лог:

```bash
tail -100 storage/logs/bot.log
```

Проверьте токен в `.env` и убедитесь, что бот не запущен вторым процессом в другом терминале.

### `file is too big` при отправке файла в бота

В стандартном режиме Telegram не отдаёт боту файлы больше 20 МБ. Бот ответит понятным сообщением и предложит загрузку через сайт.

Для файлов больше 20 МБ подключите Local Bot API (см. раздел «Большие файлы из Telegram»).

## Развёртывание на сервере (Docker)

Стек: PostgreSQL + Django (gunicorn) + Telegram-бот. БД — Docker volume; файлы — bind mount на `/srv/storage/homehub`.

### 1. Подготовка Debian-сервера

Подключитесь по SSH, установите Docker и создайте каталог хранилища:

```bash
sudo mkdir -p /srv/storage/homehub/{backup,logs,tmp}
sudo chown -R "$USER:$USER" /srv/storage/homehub
```

Установите Docker:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Выйдите из SSH и зайдите снова, чтобы группа `docker` применилась.

### 2. Клонирование проекта

```bash
git clone https://github.com/YOUR_USER/homeHub.git
cd homeHub
```

Или скопируйте проект с локальной машины:

```bash
rsync -avz --exclude '.venv' --exclude 'storage' --exclude '.git' \
  ./ user@SERVER_IP:~/homeHub/
```

### 3. Настройка `.env`

```bash
cp .env.example .env
nano .env
```

Обязательно задайте для production:

```env
DJANGO_SECRET_KEY=длинный-случайный-ключ
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=IP_СЕРВЕРА,домен.example
HOMEHUB_STORAGE_ROOT=/app/storage
POSTGRES_PASSWORD=сильный-пароль
SITE_BASE_URL=http://IP_СЕРВЕРА:8001
TELEGRAM_BOT_TOKEN=токен-от-BotFather
PROJECT_NAME=homehub
```

`POSTGRES_HOST` в Docker менять не нужно — в `docker-compose.yml` он переопределяется на `db`.

Если переносите данные со старого пути `/srv/projects/homemhub/storage`:

```bash
sudo rsync -a /srv/projects/homemhub/storage/ /srv/storage/homehub/
```

### 4. Запуск

```bash
docker compose up -d --build
```

Проверка:

```bash
docker compose ps
docker compose logs -f web
curl -I "http://127.0.0.1:${SITE_PORT:-8001}/"
```

Сайт будет доступен по `http://IP_СЕРВЕРА:8001`. Откройте порт в firewall, если нужен доступ извне:

```bash
sudo ufw allow 8001/tcp
```

### 5. Полезные команды на сервере

```bash
# логи
docker compose logs -f web
docker compose logs -f bot

# перезапуск после обновления кода
git pull
docker compose up -d --build

# остановка
docker compose down

# остановка с удалением volumes (удалит БД и файлы!)
docker compose down -v
```

### 6. Бэкап и выгрузка на носитель

Файлы приложения лежат в `/srv/storage/homehub` (в контейнере — `/app/storage`). Структура загрузок:

- без альбома: `uploads/user_{id}/{YYYY-MM-DD}/{category}/`
- в альбоме: `albums/{slug_названия}/{category}/`
- бэкапы: `backup/{YYYY-MM-DD}/`

**Два файла окружения:**

| Файл | Кто читает | Назначение |
|------|------------|------------|
| `.env` | Docker (web, bot) | Секреты, `HOMEHUB_STORAGE_ROOT=/app/storage` |
| `.env.host` | `scripts/*.sh` на сервере | Пути хоста: `HOMEHUB_STORAGE_ROOT=/srv/storage/homehub` |

На сервере один раз:

```bash
cp .env.host.example .env.host
# в .env для Docker оставьте HOMEHUB_STORAGE_ROOT=/app/storage
```

Скрипты загружают сначала `.env`, затем `.env.host` (переопределяет пути).

Скрипты в каталоге `scripts/`:

```bash
chmod +x scripts/*.sh

# ежедневный бэкап БД и конфигурации
./scripts/backup_homehub.sh

# полная копия storage на съёмный носитель
./scripts/export_storage.sh /media/usb

# только бэкапы на съёмный носитель
./scripts/export_backups.sh /media/usb
./scripts/export_backups.sh --latest /media/usb
```

Пример cron (ежедневно в 03:00):

```bash
0 3 * * * /path/to/homeHub/scripts/backup_homehub.sh >> /srv/storage/homehub/logs/backup.log 2>&1
```

Бэкап включает `.env` с секретами — храните носитель и каталог `backup/` в безопасном месте.

Ручной дамп БД (если скрипт недоступен):

```bash
docker compose exec -T db pg_dump -U homehub homehub | gzip > /srv/storage/homehub/backup/manual/homehub.sql.gz
```

### 7. HTTPS (опционально)

Для домена с TLS поставьте перед контейнером reverse proxy (Caddy или nginx) и проксируйте на `127.0.0.1:8001`. Тогда обновите `SITE_BASE_URL` и `DJANGO_ALLOWED_HOSTS` на ваш домен.


