from django.conf import settings
from django.db import models
from django.utils import timezone


class TelegramProfile(models.Model):
    """Связывает Django-пользователя с Telegram identity для авторизации команд бота."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram_profile")
    telegram_user_id = models.BigIntegerField(unique=True)
    telegram_username = models.CharField(max_length=255, blank=True)
    first_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    chat_id = models.BigIntegerField(blank=True, null=True)
    is_allowed = models.BooleanField(default=True)
    is_bot_admin = models.BooleanField(default=False)
    active_album = models.ForeignKey(
        "files.Album",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_for_profiles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram-профиль"
        verbose_name_plural = "Telegram-профили"

    def __str__(self) -> str:
        return f"{self.user} / {self.telegram_user_id}"

    @property
    def display_name(self) -> str:
        """Возвращает человекочитаемое имя для навигации: Telegram username, имя из Telegram или Django username."""
        if self.telegram_username:
            return f"@{self.telegram_username}"
        full_name = " ".join(part for part in [self.first_name, self.last_name] if part).strip()
        return full_name or self.user.get_username()


class TelegramLoginToken(models.Model):
    """Хранит одноразовый токен быстрого входа с Telegram; принимает профиль, срок действия и момент использования."""

    profile = models.ForeignKey(TelegramProfile, on_delete=models.CASCADE, related_name="login_tokens")
    token = models.CharField(max_length=128, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["token", "expires_at"], name="accounts_te_token_ee4695_idx"),
            models.Index(fields=["profile", "-created_at"], name="accounts_te_profile_3b3781_idx"),
        ]
        verbose_name = "Telegram-токен входа"
        verbose_name_plural = "Telegram-токены входа"

    def __str__(self) -> str:
        return f"{self.profile.telegram_user_id} / {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def is_active(self) -> bool:
        """Возвращает, можно ли ещё использовать токен для входа на сайт."""
        return self.consumed_at is None and self.expires_at > timezone.now()


class DictionaryEntry(models.Model):
    """Хранит одну словарную статью из JSON: позицию, заголовок и толкование для быстрой выдачи ботом."""

    position = models.PositiveIntegerField(unique=True, db_index=True)
    title = models.CharField(max_length=255, db_index=True)
    sense = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position"]
        verbose_name = "Словарная статья"
        verbose_name_plural = "Словарные статьи"

    def __str__(self) -> str:
        return f"{self.position + 1}. {self.title}"


class DictionaryProgress(models.Model):
    """Запоминает, с какой позиции Telegram-профилю нужно показать следующую порцию словаря."""

    profile = models.OneToOneField(
        TelegramProfile,
        on_delete=models.CASCADE,
        related_name="dictionary_progress",
    )
    next_position = models.PositiveIntegerField(default=0)
    last_start_position = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Прогресс словаря"
        verbose_name_plural = "Прогресс словаря"

    def __str__(self) -> str:
        return f"{self.profile.display_name}: next={self.next_position}"
