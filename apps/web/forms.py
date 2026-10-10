from django import forms

from apps.files.forms import MultipleFileInput
from apps.files.printing import PrintError, PrintService


class PrintUploadForm(forms.Form):
    """Принимает один документ, число копий и идентификатор запроса для защиты от двойной печати."""

    request_id = forms.UUIDField(widget=forms.HiddenInput)
    document = forms.FileField(
        label="Документ или фото",
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf,.doc,.docx,.odt,.jpg,.jpeg,.png,.txt"}),
    )
    copies = forms.IntegerField(label="Количество копий", min_value=1, max_value=10, initial=1)

    def clean_document(self):
        document = self.cleaned_data["document"]
        try:
            PrintService.validate_upload(document.name, document.size)
        except PrintError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return document


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
