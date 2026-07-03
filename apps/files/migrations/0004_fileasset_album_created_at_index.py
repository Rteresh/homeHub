from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0003_fileasset_poster_path_album_fileasset_album_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="fileasset",
            index=models.Index(fields=["album", "-created_at"], name="files_filea_album_i_8c0f2d_idx"),
        ),
    ]
