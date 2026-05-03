from django import forms

from apps.files.models import FileAsset


class FileUploadForm(forms.Form):
    """Принимает файл из веб-интерфейса и необязательную категорию для первичной классификации."""

    file = forms.FileField(label="Файл")
    category = forms.ChoiceField(
        label="Категория",
        required=False,
        choices=[("", "Определить автоматически"), *FileAsset.Category.choices],
    )


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

