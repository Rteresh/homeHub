from django import forms

from apps.files.albums import AlbumService
from apps.files.models import Album, FileAsset


class MultipleFileInput(forms.FileInput):
    """Разрешает выбор нескольких файлов в одном input type=file."""

    allow_multiple_selected = True

    def __init__(self, attrs=None):
        super().__init__(attrs)
        self.attrs["multiple"] = True


class FileUploadForm(forms.Form):
    """Принимает один или несколько файлов, необязательную категорию и альбом для группировки."""

    files = forms.FileField(
        label="Файлы",
        widget=MultipleFileInput(),
        required=False,
    )
    category = forms.ChoiceField(
        label="Категория",
        required=False,
        choices=[("", "Определить автоматически"), *FileAsset.Category.choices],
    )
    album = forms.ModelChoiceField(
        label="Альбом",
        required=False,
        queryset=Album.objects.none(),
        empty_label="Без альбома",
    )

    def __init__(self, *args, user=None, uploaded_files=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.uploaded_files = uploaded_files or []
        if user is not None and user.is_authenticated:
            self.fields["album"].queryset = AlbumService.list_for_user(user)

    def clean(self):
        cleaned_data = super().clean()
        files = self.uploaded_files or ([cleaned_data["files"]] if cleaned_data.get("files") else [])
        if not files:
            raise forms.ValidationError("Выберите хотя бы один файл.")
        cleaned_data["files"] = files
        return cleaned_data


class FileAssetAdminForm(forms.ModelForm):
    """Добавляет upload-поле в Django admin, чтобы администратор загружал файл без ручного storage_path."""

    upload_file = forms.FileField(label="Загрузить файл", required=False)

    class Meta:
        model = FileAsset
        fields = "__all__"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["original_name"].required = False
        self.fields["storage_path"].required = False
        self.fields["size_bytes"].required = False
        self.fields["checksum"].required = False

    def clean(self):
        cleaned_data = super().clean()
        if not self.instance.pk and not cleaned_data.get("upload_file"):
            raise forms.ValidationError("Для нового файла нужно выбрать файл для загрузки.")
        return cleaned_data

