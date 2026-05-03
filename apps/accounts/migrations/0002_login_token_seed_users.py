import django.db.models.deletion
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations, models


def seed_telegram_users(apps, schema_editor):
    """Создаёт двух разрешённых Telegram-пользователей; первый получает флаг администратора бота и staff-доступ."""
    User = apps.get_model("auth", "User")
    TelegramProfile = apps.get_model("accounts", "TelegramProfile")

    users = [
        {"telegram_id": 477542023, "username": "telegram_477542023", "is_admin": True},
        {"telegram_id": 893988585, "username": "telegram_893988585", "is_admin": False},
    ]

    for item in users:
        user, created = User.objects.get_or_create(
            username=item["username"],
            defaults={
                "is_active": True,
                "is_staff": item["is_admin"],
                "is_superuser": False,
            },
        )
        if created:
            user.password = make_password(None)
            user.save(update_fields=["password"])
        elif item["is_admin"] and not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])

        TelegramProfile.objects.update_or_create(
            telegram_user_id=item["telegram_id"],
            defaults={
                "user": user,
                "is_allowed": True,
                "is_bot_admin": item["is_admin"],
            },
        )


def unseed_telegram_users(apps, schema_editor):
    """Удаляет только преднастроенные Telegram-профили; Django-пользователей оставляет, чтобы не терять связанные данные."""
    TelegramProfile = apps.get_model("accounts", "TelegramProfile")
    TelegramProfile.objects.filter(telegram_user_id__in=[477542023, 893988585]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TelegramLoginToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(db_index=True, max_length=128, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="login_tokens",
                        to="accounts.telegramprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Telegram-токен входа",
                "verbose_name_plural": "Telegram-токены входа",
            },
        ),
        migrations.AddIndex(
            model_name="telegramlogintoken",
            index=models.Index(fields=["token", "expires_at"], name="accounts_te_token_ee4695_idx"),
        ),
        migrations.AddIndex(
            model_name="telegramlogintoken",
            index=models.Index(fields=["profile", "-created_at"], name="accounts_te_profile_3b3781_idx"),
        ),
        migrations.RunPython(seed_telegram_users, unseed_telegram_users),
    ]
