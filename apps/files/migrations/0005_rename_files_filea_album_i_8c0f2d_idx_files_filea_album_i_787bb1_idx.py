from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0004_fileasset_album_created_at_index"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="fileasset",
            new_name="files_filea_album_i_787bb1_idx",
            old_name="files_filea_album_i_8c0f2d_idx",
        ),
    ]
