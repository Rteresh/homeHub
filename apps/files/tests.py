from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.files.models import FileAsset
from apps.files.permissions import FileAccessService
from apps.files.services import FileQueryService
from apps.files.storage import LocalFileStorage, StoragePathError


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


class FileUploadViewTests(TestCase):
    def test_authenticated_user_can_upload_file(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                user = get_user_model().objects.create_user(username="owner", password="password")
                self.client.force_login(user)
                uploaded_file = SimpleUploadedFile("note.txt", b"hello homehub", content_type="text/plain")

                response = self.client.post(reverse("file-upload"), {"file": uploaded_file})

                self.assertRedirects(response, reverse("file-list"))
                asset = FileAsset.objects.get(owner=user)
                self.assertEqual(asset.original_name, "note.txt")
                self.assertEqual(asset.status, FileAsset.Status.READY)
                self.assertEqual(asset.category, FileAsset.Category.DOCUMENT)
                self.assertTrue((Path(tmp_dir) / asset.storage_path).is_file())

    def test_anonymous_user_cannot_open_upload_page(self):
        response = self.client.get(reverse("file-upload"))

        self.assertEqual(response.status_code, 302)
