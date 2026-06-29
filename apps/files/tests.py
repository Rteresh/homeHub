from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import io
import zipfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.files.albums import AlbumService
from apps.files.models import Album, FileAsset
from apps.files.permissions import FileAccessService
from apps.files.services import FileIngestionService, FileQueryService
from apps.files.storage import LocalFileStorage, StoragePathError
from apps.files.video_poster import build_poster_relative_path, generate_video_poster


class FileAccessServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="password")
        self.other = User.objects.create_user(username="other", password="password")
        self.admin = User.objects.create_user(username="admin", password="password", is_staff=True)
        self.asset = FileAsset.objects.create(
            owner=self.owner,
            original_name="photo.jpg",
            storage_path="uploads/owner/photo.jpg",
            category=FileAsset.Category.PHOTO,
            status=FileAsset.Status.READY,
        )

    def test_owner_can_download_own_file(self):
        self.assertTrue(FileAccessService.can_download(self.owner, self.asset))

    def test_other_user_cannot_download_foreign_file(self):
        self.assertFalse(FileAccessService.can_download(self.other, self.asset))

    def test_admin_can_download_any_file(self):
        self.assertTrue(FileAccessService.can_download(self.admin, self.asset))


class FileQueryServiceTests(TestCase):
    def test_regular_user_sees_only_own_files(self):
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="password")
        other = User.objects.create_user(username="other", password="password")
        own_asset = FileAsset.objects.create(owner=owner, original_name="own.txt", storage_path="uploads/own.txt")
        FileAsset.objects.create(owner=other, original_name="other.txt", storage_path="uploads/other.txt")

        visible_ids = set(FileQueryService.visible_to(owner).values_list("id", flat=True))

        self.assertEqual(visible_ids, {own_asset.id})


class LocalFileStorageTests(TestCase):
    def test_rejects_path_traversal(self):
        with TemporaryDirectory() as tmp_dir:
            storage = LocalFileStorage(root=Path(tmp_dir))

            with self.assertRaises(StoragePathError):
                storage.resolve_private_path("../secret.txt")

    def test_accepts_path_inside_storage_root(self):
        with TemporaryDirectory() as tmp_dir:
            storage = LocalFileStorage(root=Path(tmp_dir))

            resolved_path = storage.resolve_private_path("uploads/file.txt")

            self.assertTrue(resolved_path.is_relative_to(Path(tmp_dir).resolve()))


class StorageUploadPathTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="password")

    def test_upload_without_album_uses_user_date_and_category(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                uploaded_file = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
                asset = FileIngestionService.create_from_uploaded_file(owner=self.owner, uploaded_file=uploaded_file)

                today = timezone.localtime().strftime("%Y-%m-%d")
                expected_prefix = f"uploads/user_{self.owner.id}/{today}/document/"
                self.assertTrue(asset.storage_path.startswith(expected_prefix))
                self.assertTrue((Path(tmp_dir) / asset.storage_path).is_file())

    def test_upload_to_album_uses_album_slug_and_category(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                album = AlbumService.create_album(self.owner, "Отпуск")
                uploaded_file = SimpleUploadedFile("photo.jpg", b"fake-image", content_type="image/jpeg")
                asset = FileIngestionService.create_from_uploaded_file(
                    owner=self.owner,
                    uploaded_file=uploaded_file,
                    album=album,
                )

                self.assertTrue(asset.storage_path.startswith(f"albums/album-{album.public_id.hex[:8]}/photo/"))
                self.assertTrue((Path(tmp_dir) / asset.storage_path).is_file())

    def test_video_poster_path_is_next_to_video_file(self):
        storage_path = "uploads/user_1/2026-06-29/video/abc_clip.mp4"
        public_id = "11111111-2222-3333-4444-555555555555"
        poster_path = build_poster_relative_path(storage_path, public_id)
        self.assertEqual(
            poster_path,
            "uploads/user_1/2026-06-29/video/posters/11111111-2222-3333-4444-555555555555.jpg",
        )


class FileUploadViewTests(TestCase):
    def test_authenticated_user_can_upload_file(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                user = get_user_model().objects.create_user(username="owner", password="password")
                self.client.force_login(user)
                uploaded_file = SimpleUploadedFile("note.txt", b"hello homehub", content_type="text/plain")

                response = self.client.post(reverse("file-upload"), {"files": uploaded_file})

                self.assertRedirects(response, reverse("file-list"))
                asset = FileAsset.objects.get(owner=user)
                self.assertEqual(asset.original_name, "note.txt")
                self.assertEqual(asset.status, FileAsset.Status.READY)
                self.assertEqual(asset.category, FileAsset.Category.DOCUMENT)
                self.assertTrue((Path(tmp_dir) / asset.storage_path).is_file())

    def test_authenticated_user_can_upload_multiple_files(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                user = get_user_model().objects.create_user(username="owner", password="password")
                self.client.force_login(user)
                first = SimpleUploadedFile("one.txt", b"first", content_type="text/plain")
                second = SimpleUploadedFile("two.txt", b"second", content_type="text/plain")

                response = self.client.post(reverse("file-upload"), {"files": [first, second]})

                self.assertRedirects(response, reverse("file-list"))
                self.assertEqual(FileAsset.objects.filter(owner=user).count(), 2)
                self.assertEqual(
                    set(FileAsset.objects.filter(owner=user).values_list("original_name", flat=True)),
                    {"one.txt", "two.txt"},
                )

    def test_anonymous_user_cannot_open_upload_page(self):
        response = self.client.get(reverse("file-upload"))

        self.assertEqual(response.status_code, 302)


class AlbumServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="password")
        self.other = User.objects.create_user(username="other", password="password")
        from apps.accounts.models import TelegramProfile

        TelegramProfile.objects.create(user=self.owner, telegram_user_id=1001, is_allowed=True)
        TelegramProfile.objects.create(user=self.other, telegram_user_id=1002, is_allowed=True)

    def test_create_album_and_attach_uploaded_file(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                album = AlbumService.create_album(self.owner, "Отпуск")
                uploaded_file = SimpleUploadedFile("photo.jpg", b"fake-image", content_type="image/jpeg")
                asset = FileIngestionService.create_from_uploaded_file(
                    owner=self.owner,
                    uploaded_file=uploaded_file,
                    album=album,
                )

                self.assertEqual(asset.album_id, album.id)
                self.assertEqual(Album.objects.filter(owner=self.owner).count(), 1)

    def test_homehub_member_sees_other_users_albums(self):
        album = AlbumService.create_album(self.owner, "Семейный")
        visible = AlbumService.list_for_user(self.other)
        self.assertIn(album, list(visible))

    def test_homehub_member_can_select_other_users_album(self):
        album = AlbumService.create_album(self.owner, "Семейный")
        profile = self.other.telegram_profile
        AlbumService.set_active_album(profile, album)
        profile.refresh_from_db()
        self.assertEqual(profile.active_album_id, album.id)

    def test_shared_album_files_visible_to_other_member(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                album = AlbumService.create_album(self.owner, "Семейный")
                uploaded_file = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
                asset = FileIngestionService.create_from_uploaded_file(
                    owner=self.owner,
                    uploaded_file=uploaded_file,
                    album=album,
                )
                visible_ids = set(FileQueryService.visible_to(self.other).values_list("id", flat=True))
                self.assertIn(asset.id, visible_ids)
                self.assertTrue(FileAccessService.can_download(self.other, asset))


class VideoPosterServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="password")

    def test_generate_video_poster_without_ffmpeg_returns_none(self):
        with TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)
            video_path = storage_root / "uploads/user_1/video.mp4"
            video_path.parent.mkdir(parents=True)
            video_path.write_bytes(b"fake-video")
            asset = FileAsset.objects.create(
                owner=self.owner,
                original_name="video.mp4",
                storage_path="uploads/user_1/video.mp4",
                category=FileAsset.Category.VIDEO,
                status=FileAsset.Status.READY,
            )

            with patch("apps.files.video_poster.shutil.which", return_value=None):
                result = generate_video_poster(asset, storage=LocalFileStorage(root=storage_root))

            self.assertIsNone(result)
            asset.refresh_from_db()
            self.assertEqual(asset.poster_path, "")

    def test_generate_video_poster_success(self):
        with TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)
            video_path = storage_root / "uploads/user_1/video.mp4"
            video_path.parent.mkdir(parents=True)
            video_path.write_bytes(b"fake-video")
            asset = FileAsset.objects.create(
                owner=self.owner,
                original_name="video.mp4",
                storage_path="uploads/user_1/video.mp4",
                category=FileAsset.Category.VIDEO,
                status=FileAsset.Status.READY,
            )

            def fake_run(command, **kwargs):
                poster_file = Path(command[-1])
                poster_file.parent.mkdir(parents=True, exist_ok=True)
                poster_file.write_bytes(b"jpeg")

            with patch("apps.files.video_poster.shutil.which", return_value="/usr/bin/ffmpeg"):
                with patch("apps.files.video_poster.subprocess.run", side_effect=fake_run):
                    result = generate_video_poster(asset, storage=LocalFileStorage(root=storage_root))

            self.assertIsNotNone(result)
            asset.refresh_from_db()
            self.assertEqual(result, f"uploads/user_1/posters/{asset.public_id}.jpg")
            self.assertEqual(asset.poster_path, result)


class BulkMediaActionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="password")
        self.other = User.objects.create_user(username="other", password="password")
        from apps.accounts.models import TelegramProfile

        TelegramProfile.objects.create(user=self.owner, telegram_user_id=2001, is_allowed=True)
        TelegramProfile.objects.create(user=self.other, telegram_user_id=2002, is_allowed=True)

    def _create_ready_file(self, owner, name: str, content: bytes, tmp_dir: Path) -> FileAsset:
        storage = LocalFileStorage(root=tmp_dir)
        relative_path = storage.build_upload_path(owner.id, name, category=FileAsset.Category.PHOTO)
        file_path = storage.resolve_private_path(relative_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        return FileAsset.objects.create(
            owner=owner,
            original_name=name,
            storage_path=relative_path,
            category=FileAsset.Category.PHOTO,
            status=FileAsset.Status.READY,
            size_bytes=len(content),
        )

    def test_owner_bulk_download_returns_zip_for_multiple_files(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                first = self._create_ready_file(self.owner, "one.jpg", b"first-image", Path(tmp_dir))
                second = self._create_ready_file(self.owner, "two.jpg", b"second-image", Path(tmp_dir))
                self.client.force_login(self.owner)

                response = self.client.post(
                    reverse("media-bulk-download"),
                    {"public_ids": [str(first.public_id), str(second.public_id)]},
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/zip")
                archive_bytes = b"".join(response.streaming_content)
                with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
                    self.assertEqual(set(archive.namelist()), {"one.jpg", "two.jpg"})
                    self.assertEqual(archive.read("one.jpg"), b"first-image")
                    self.assertEqual(archive.read("two.jpg"), b"second-image")

    def test_owner_bulk_download_single_file_is_not_zip(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                asset = self._create_ready_file(self.owner, "solo.jpg", b"solo-image", Path(tmp_dir))
                self.client.force_login(self.owner)

                response = self.client.post(
                    reverse("media-bulk-download"),
                    {"public_ids": [str(asset.public_id)]},
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Disposition"], 'attachment; filename="solo.jpg"')
                self.assertEqual(b"".join(response.streaming_content), b"solo-image")

    def test_owner_bulk_delete_marks_files_deleted_and_redirects_to_media_library(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                first = self._create_ready_file(self.owner, "one.jpg", b"first-image", Path(tmp_dir))
                second = self._create_ready_file(self.owner, "two.jpg", b"second-image", Path(tmp_dir))
                self.client.force_login(self.owner)

                response = self.client.post(
                    reverse("media-bulk-delete"),
                    {
                        "public_ids": [str(first.public_id), str(second.public_id)],
                        "return_to": reverse("media-library"),
                    },
                )

                self.assertRedirects(response, reverse("media-library"))
                first.refresh_from_db()
                second.refresh_from_db()
                self.assertEqual(first.status, FileAsset.Status.DELETED)
                self.assertEqual(second.status, FileAsset.Status.DELETED)

    def test_stranger_cannot_bulk_delete_foreign_files(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                asset = self._create_ready_file(self.owner, "secret.jpg", b"secret", Path(tmp_dir))
                self.client.force_login(self.other)

                response = self.client.post(
                    reverse("media-bulk-delete"),
                    {
                        "public_ids": [str(asset.public_id)],
                        "return_to": reverse("media-library"),
                    },
                )

                self.assertRedirects(response, reverse("media-library"))
                asset.refresh_from_db()
                self.assertEqual(asset.status, FileAsset.Status.READY)

    def test_album_member_can_bulk_download_shared_files(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                album = AlbumService.create_album(self.owner, "Семейный")
                asset = self._create_ready_file(self.owner, "shared.jpg", b"shared-image", Path(tmp_dir))
                asset.album = album
                asset.save(update_fields=["album"])
                self.client.force_login(self.other)

                response = self.client.post(
                    reverse("media-bulk-download"),
                    {"public_ids": [str(asset.public_id)]},
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"shared-image")

    def test_album_member_cannot_bulk_delete_shared_files(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                album = AlbumService.create_album(self.owner, "Семейный")
                asset = self._create_ready_file(self.owner, "shared.jpg", b"shared-image", Path(tmp_dir))
                asset.album = album
                asset.save(update_fields=["album"])
                self.client.force_login(self.other)

                response = self.client.post(
                    reverse("media-bulk-delete"),
                    {
                        "public_ids": [str(asset.public_id)],
                        "return_to": reverse("media-library"),
                    },
                )

                self.assertRedirects(response, reverse("media-library"))
                asset.refresh_from_db()
                self.assertEqual(asset.status, FileAsset.Status.READY)

    def test_bulk_download_with_empty_ids_returns_bad_request(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("media-bulk-download"), {"public_ids": []})
        self.assertEqual(response.status_code, 400)

    def test_bulk_delete_with_empty_ids_returns_bad_request(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("media-bulk-delete"), {"public_ids": []})
        self.assertEqual(response.status_code, 400)


class AudioPreviewTests(TestCase):
    def test_owner_can_preview_audio_inline(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                user = get_user_model().objects.create_user(username="owner", password="password")
                storage = LocalFileStorage(root=Path(tmp_dir))
                relative_path = storage.build_upload_path(user.id, "track.mp3", category=FileAsset.Category.AUDIO)
                file_path = storage.resolve_private_path(relative_path)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(b"fake-mp3")
                asset = FileAsset.objects.create(
                    owner=user,
                    original_name="track.mp3",
                    storage_path=relative_path,
                    mime_type="audio/mpeg",
                    category=FileAsset.Category.AUDIO,
                    status=FileAsset.Status.READY,
                    size_bytes=8,
                )
                self.client.force_login(user)

                response = self.client.get(reverse("file-preview", kwargs={"public_id": asset.public_id}))

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "audio/mpeg")
                self.assertIn('inline; filename="track.mp3"', response["Content-Disposition"])
                self.assertEqual(b"".join(response.streaming_content), b"fake-mp3")

    def test_audio_appears_in_media_library(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                user = get_user_model().objects.create_user(username="owner", password="password")
                FileAsset.objects.create(
                    owner=user,
                    original_name="voice.ogg",
                    storage_path="uploads/voice.ogg",
                    mime_type="audio/ogg",
                    category=FileAsset.Category.AUDIO,
                    status=FileAsset.Status.READY,
                )
                self.client.force_login(user)

                response = self.client.get(reverse("media-library"))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "voice.ogg")
                self.assertContains(response, "Аудио")
