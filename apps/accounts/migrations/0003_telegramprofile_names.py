from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_login_token_seed_users"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramprofile",
            name="first_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="telegramprofile",
            name="last_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="telegramprofile",
            name="telegram_username",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
