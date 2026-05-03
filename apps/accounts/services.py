from datetime import timedelta
from secrets import token_urlsafe

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import TelegramLoginToken, TelegramProfile


class TelegramIdentityService:
    """Находит Django-пользователя по Telegram ID; сервис нужен bot middleware перед выполнением команд."""

    @staticmethod
    def find_allowed_user(telegram_user_id: int):
        return (
            get_user_model()
            .objects.filter(
                telegram_profile__telegram_user_id=telegram_user_id,
                telegram_profile__is_allowed=True,
                is_active=True,
            )
            .select_related("telegram_profile")
            .first()
        )

    @staticmethod
    def bind_user(user, telegram_user_id: int, chat_id: int | None = None) -> TelegramProfile:
        profile, _created = TelegramProfile.objects.update_or_create(
            user=user,
            defaults={
                "telegram_user_id": telegram_user_id,
                "chat_id": chat_id,
                "is_allowed": True,
            },
        )
        return profile


class TelegramLoginService:
    """Создаёт и погашает одноразовые ссылки входа, которые Telegram-бот отправляет разрешённым пользователям."""

    @staticmethod
    def create_login_token(profile: TelegramProfile, ttl_minutes: int = 10) -> TelegramLoginToken:
        return TelegramLoginToken.objects.create(
            profile=profile,
            token=token_urlsafe(32),
            expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
        )

    @staticmethod
    def consume_token(raw_token: str) -> TelegramLoginToken | None:
        with transaction.atomic():
            login_token = (
                TelegramLoginToken.objects.select_for_update()
                .select_related("profile__user")
                .filter(token=raw_token)
                .first()
            )
            if not login_token or not login_token.is_active:
                return None
            if not login_token.profile.is_allowed or not login_token.profile.user.is_active:
                return None
            login_token.consumed_at = timezone.now()
            login_token.save(update_fields=["consumed_at"])
            return login_token
