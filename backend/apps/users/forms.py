"""User management forms."""
from django import forms
from django.forms import ChoiceField

from apps.accounts.models import User
from common.choices import UserRole

_INPUT = {"class": "form-control"}


def _is_superadmin_actor(user) -> bool:
    return bool(
        user
        and (
            getattr(user, "is_superuser", False)
            or getattr(user, "is_superadmin", False)
        )
    )


class UserCreateForm(forms.ModelForm):
    """Create a user with an initial password. No public registration."""

    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs=_INPUT),
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs=_INPUT),
    )

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "role", "allow_db_access")
        widgets = {
            "email": forms.EmailInput(attrs=_INPUT),
            "first_name": forms.TextInput(attrs=_INPUT),
            "last_name": forms.TextInput(attrs=_INPUT),
            "role": forms.Select(attrs=_INPUT),
        }

    def __init__(self, *args, request_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_user = request_user
        self.fields["first_name"].required = True
        role_field = self.fields["role"]
        if isinstance(role_field, ChoiceField):
            if _is_superadmin_actor(request_user):
                role_field.choices = [
                    (UserRole.ADMIN, "App Admin"),
                    (UserRole.EXPERT, "BOQ Expert"),
                ]
            else:
                # Peer Admins cannot create other Admins.
                role_field.choices = [
                    (UserRole.EXPERT, "BOQ Expert"),
                ]

    def clean(self):
        cleaned = super().clean()
        if cleaned is None:
            return cleaned
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        if cleaned.get("role") == UserRole.ADMIN:
            if not _is_superadmin_actor(self.request_user):
                self.add_error("role", "Only Superadmin can create Admin users.")
            cleaned["allow_db_access"] = True
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserEditForm(forms.ModelForm):
    """Edit an existing user's profile, role and active state."""

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "role", "allow_db_access")
        widgets = {
            "email": forms.EmailInput(attrs=_INPUT),
            "first_name": forms.TextInput(attrs=_INPUT),
            "last_name": forms.TextInput(attrs=_INPUT),
            "role": forms.Select(attrs=_INPUT),
        }

    def __init__(self, *args, request_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_user = request_user
        self.fields["first_name"].required = True
        role_field = self.fields["role"]
        if isinstance(role_field, ChoiceField):
            if _is_superadmin_actor(request_user):
                role_field.choices = [
                    (UserRole.ADMIN, "App Admin"),
                    (UserRole.EXPERT, "BOQ Expert"),
                ]
            else:
                role_field.choices = [
                    (UserRole.EXPERT, "BOQ Expert"),
                ]
        if self.instance and self.request_user and self.instance.pk == self.request_user.pk:
            self.fields["email"].disabled = True
            self.fields["email"].help_text = "You cannot change your own email."

    def clean(self):
        cleaned = super().clean()
        if cleaned is None:
            return cleaned
        if self.instance and self.request_user and self.instance.pk == self.request_user.pk:
            cleaned["email"] = self.instance.email

        if not _is_superadmin_actor(self.request_user):
            # Admins may only keep Experts as Experts — never promote to Admin.
            cleaned["role"] = UserRole.EXPERT
            if self.instance and self.instance.role == UserRole.ADMIN:
                self.add_error(None, "Only Superadmin can manage Admin users.")

        if cleaned.get("role") == UserRole.ADMIN:
            cleaned["allow_db_access"] = True

        return cleaned
