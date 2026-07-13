"""BOQ upload form."""
from django import forms

from apps.boq.models import BOQ

_EXCEL_EXTS = (".xlsx", ".xlsm")
_MAKE_LIST_EXTS = _EXCEL_EXTS + (".pdf",)


def _validate_excel(f):
    if f and not (f.name or "").lower().endswith(_EXCEL_EXTS):
        raise forms.ValidationError("Please upload an .xlsx or .xlsm Excel file.")
    return f


def _validate_make_list(f):
    if f and not (f.name or "").lower().endswith(_MAKE_LIST_EXTS):
        raise forms.ValidationError("Please upload an .xlsx, .xlsm, or .pdf make list.")
    return f


class BOQUploadForm(forms.Form):
    boq_name = forms.CharField(
        max_length=255,
        label="BOQ name (must be unique)",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "e.g. Tower-A Fire Fighting",
            }
        ),
        help_text="Each BOQ needs a unique name. It is used for the extract JSON folder.",
    )
    uploaded_file = forms.FileField(
        label="BOQ workbook (.xlsx or .xlsm)",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".xlsx,.xlsm"}
        ),
    )
    make_list_file = forms.FileField(
        label="Make list (.xlsx, .xlsm, or .pdf, optional)",
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".xlsx,.xlsm,.pdf"}
        ),
    )

    def clean_boq_name(self):
        name = (self.cleaned_data.get("boq_name") or "").strip()
        if not name:
            raise forms.ValidationError("BOQ name is required.")
        if BOQ.objects.filter(boq_name__iexact=name).exists():
            raise forms.ValidationError(
                "A BOQ with this name already exists. Choose a different name."
            )
        return name

    def clean_uploaded_file(self):
        return _validate_excel(self.cleaned_data["uploaded_file"])

    def clean_make_list_file(self):
        return _validate_make_list(self.cleaned_data.get("make_list_file"))
