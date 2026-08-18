from django import forms

from apps.files.forms import MultipleFileInput


class DirectUploadForm(forms.Form):
    """Форма выгрузки файлов с клиентского устройства в произвольный каталог на сервере."""

    files = forms.FileField(
        label="Файлы",
        widget=MultipleFileInput(),
        required=False,
    )
    target_dir = forms.CharField(
        label="Путь на сервере",
        max_length=512,
        widget=forms.TextInput(attrs={"placeholder": "/srv/incoming/docs", "autocomplete": "off"}),
    )

    def __init__(self, *args, uploaded_files=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.uploaded_files = uploaded_files or []

    def clean(self):
        cleaned_data = super().clean()
        files = self.uploaded_files or ([cleaned_data["files"]] if cleaned_data.get("files") else [])
        if not files:
            raise forms.ValidationError("Выберите хотя бы один файл.")
        cleaned_data["files"] = files
        return cleaned_data
