from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_telegramprofile_names"),
    ]

    operations = [
        migrations.CreateModel(
            name="DictionaryEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField(db_index=True, unique=True)),
                ("title", models.CharField(db_index=True, max_length=255)),
                ("sense", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Словарная статья",
                "verbose_name_plural": "Словарные статьи",
                "ordering": ["position"],
            },
        ),
        migrations.CreateModel(
            name="DictionaryProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("next_position", models.PositiveIntegerField(default=0)),
                ("last_start_position", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "profile",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dictionary_progress",
                        to="accounts.telegramprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Прогресс словаря",
                "verbose_name_plural": "Прогресс словаря",
            },
        ),
    ]
