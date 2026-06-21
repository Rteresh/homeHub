import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def load_local_env(env_path: Path) -> None:
    """Загружает пары KEY=VALUE из локального .env, чтобы Django и бот брали настройки без ручного export."""
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    """Возвращает boolean из переменной окружения `name`; нужна для безопасной настройки DEBUG и похожих флагов."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    """Возвращает список строк из comma-separated переменной окружения `name`; используется для hosts и allowlist."""
    raw_value = os.environ.get(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def database_settings() -> dict[str, object]:
    """Возвращает настройки БД из окружения; PostgreSQL является основным движком, SQLite оставлен для локальных аварийных проверок."""
    engine = os.environ.get("DATABASE_ENGINE", "postgresql").strip().lower()
    if engine == "sqlite":
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("SQLITE_PATH", BASE_DIR / "db.sqlite3"),
        }

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "homehub"),
        "USER": os.environ.get("POSTGRES_USER", "homehub"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "homehub"),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(os.environ.get("POSTGRES_CONN_MAX_AGE", "60")),
    }


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-homehub-secret-key")
DEBUG = env_bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.files",
    "apps.web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "homehub.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.account_display_name",
            ],
        },
    },
]

WSGI_APPLICATION = "homehub.wsgi.application"
ASGI_APPLICATION = "homehub.asgi.application"

DATABASES = {"default": database_settings()}

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Minsk"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
HOMEHUB_STORAGE_ROOT = Path(os.environ.get("HOMEHUB_STORAGE_ROOT", BASE_DIR / "storage")).resolve()

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "file-list"
LOGOUT_REDIRECT_URL = "login"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TELEGRAM_DOWNLOAD_TIMEOUT = int(os.environ.get("TELEGRAM_DOWNLOAD_TIMEOUT", "300"))
TELEGRAM_API_BASE_URL = os.environ.get("TELEGRAM_API_BASE_URL", "").rstrip("/")
TELEGRAM_LOCAL_MODE = env_bool("TELEGRAM_LOCAL_MODE", default=False)
TELEGRAM_LOCAL_FILES_PATH = os.environ.get("TELEGRAM_LOCAL_FILES_PATH", "").strip()
