"""BOQ upload form."""
from django import forms

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
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "e.g. Tower-A Fire Fighting",
            }
        ),
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

    def clean_uploaded_file(self):
        return _validate_excel(self.cleaned_data["uploaded_file"])

    def clean_make_list_file(self):
        return _validate_make_list(self.cleaned_data.get("make_list_file"))
