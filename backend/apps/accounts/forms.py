"""Authentication forms."""
from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm
from django.contrib.auth import get_user_model

User = get_user_model()


class EmailLoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "you@example.com", "autofocus": True}
        )
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Password"}
        )
    )

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email")
        password = cleaned.get("password")
        if email and password:
            email = User.objects.normalize_email(email).lower()
            cleaned["email"] = email
            self.user = authenticate(self.request, username=email, password=password)
            if self.user is None:
                raise forms.ValidationError("Invalid email or password.")
            if not self.user.is_active:
                raise forms.ValidationError("This account is inactive.")
        return cleaned

    def get_user(self):
        return self.user


class RegisteredEmailPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": "form-control", "required": True, "autofocus": True}
        )
    )

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"]).lower()
        if not User.objects.filter(email__iexact=email, is_active=True).exists():
            raise forms.ValidationError("This email is not registered.")
        return email


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name")
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
        }


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})
            field.help_text = ""
