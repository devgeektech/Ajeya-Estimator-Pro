"""BOQ upload form."""
from django import forms

_EXCEL_EXTS = (".xlsx", ".xlsm")


def _validate_excel(f):
    if f and not (f.name or "").lower().endswith(_EXCEL_EXTS):
        raise forms.ValidationError("Please upload an .xlsx Excel file.")
    return f


class BOQUploadForm(forms.Form):
    boq_name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Tower-A Fire Fighting"}),
    )
    uploaded_file = forms.FileField(
        label="BOQ workbook (.xlsx)",
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".xlsx"}),
    )
    make_list_file = forms.FileField(
        label="Make list (.xlsx, optional)",
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".xlsx"}),
    )

    def clean_uploaded_file(self):
        return _validate_excel(self.cleaned_data["uploaded_file"])

    def clean_make_list_file(self):
        return _validate_excel(self.cleaned_data.get("make_list_file"))
