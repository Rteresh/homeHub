from django.core.management.base import BaseCommand

from apps.files.models import FileAsset
from apps.files.video_poster import generate_video_poster


class Command(BaseCommand):
    help = "Генерирует JPEG-обложки для видео без poster_path."

    def handle(self, *args, **options):
        queryset = FileAsset.objects.filter(
            category=FileAsset.Category.VIDEO,
            status=FileAsset.Status.READY,
            poster_path="",
        ).exclude(storage_path="")
        created = 0
        for asset in queryset.iterator():
            if generate_video_poster(asset):
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Создано обложек: {created}"))
