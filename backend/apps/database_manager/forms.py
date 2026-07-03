"""Database management forms."""
from django import forms


class DatabaseUploadForm(forms.Form):
    name = forms.CharField(
        label="Database Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Master Rates Q3 2026"}),
    )
    workbook = forms.FileField(
        label="Master database workbook (.xlsx)",
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".xlsx"}),
    )

    def clean_workbook(self):
        f = self.cleaned_data["workbook"]
        name = (f.name or "").lower()
        if not name.endswith((".xlsx", ".xlsm")):
            raise forms.ValidationError("Please upload an .xlsx Excel workbook.")
        return f
