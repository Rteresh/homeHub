from django.contrib import admin

from apps.accounts.models import TelegramLoginToken, TelegramProfile


@admin.register(TelegramProfile)
class TelegramProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "telegram_user_id",
        "telegram_username",
        "first_name",
        "last_name",
        "chat_id",
        "is_allowed",
        "is_bot_admin",
        "updated_at",
    )
    list_filter = ("is_allowed", "is_bot_admin")
    search_fields = ("user__username", "telegram_user_id", "telegram_username", "first_name", "last_name", "chat_id")


@admin.register(TelegramLoginToken)
class TelegramLoginTokenAdmin(admin.ModelAdmin):
    list_display = ("profile", "expires_at", "consumed_at", "created_at")
    list_filter = ("expires_at", "consumed_at")
    search_fields = ("profile__user__username", "profile__telegram_user_id", "token")
    readonly_fields = ("created_at",)
