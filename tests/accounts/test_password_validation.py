"""Tests for password complexity validation (min 6 chars, letters, numbers, symbols)."""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.forms import StyledSetPasswordForm
from apps.accounts.validators import ComplexityPasswordValidator
from apps.users.forms import UserCreateForm
from common.choices import UserRole

User = get_user_model()


class ComplexityPasswordValidatorTests(TestCase):
    def setUp(self):
        self.validator = ComplexityPasswordValidator(min_length=6)

    def test_valid_password_passes(self):
        # 6 characters with letter, number, and symbol
        self.validator.validate("Pass1@")
        self.validator.validate("Secret#9")
        self.validator.validate("Abc$12")

    def test_short_password_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("P1@")
        self.assertIn("at least 6 characters", str(ctx.exception))

    def test_missing_letter_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("12345@#")
        self.assertIn("at least one letter", str(ctx.exception))

    def test_missing_number_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("Password@")
        self.assertIn("at least one number", str(ctx.exception))

    def test_missing_symbol_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate("Password123")
        self.assertIn("at least one special symbol", str(ctx.exception))

    def test_django_validate_password_pipeline_enforces_complexity(self):
        with self.assertRaises(ValidationError):
            validate_password("simple")

        # Valid 6 char complex password passes Django pipeline
        validate_password("Pass1@")


class UserCreateFormPasswordValidationTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(
            email="super@example.com", password="ComplexPass123!"
        )

    def test_user_creation_with_weak_password_rejected(self):
        form = UserCreateForm(
            data={
                "email": "expert_new@example.com",
                "first_name": "Test",
                "last_name": "User",
                "role": UserRole.EXPERT,
                "password1": "weakpass",
                "password2": "weakpass",
                "allow_db_access": False,
            },
            request_user=self.superadmin,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("password1", form.errors)

    def test_user_creation_with_valid_complex_password_succeeds(self):
        form = UserCreateForm(
            data={
                "email": "expert_new@example.com",
                "first_name": "Test",
                "last_name": "User",
                "role": UserRole.EXPERT,
                "password1": "Pass1@",
                "password2": "Pass1@",
                "allow_db_access": False,
            },
            request_user=self.superadmin,
        )
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertTrue(user.check_password("Pass1@"))


class StyledSetPasswordFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user_reset@example.com", password="ComplexPass123!"
        )

    def test_set_password_weak_rejected(self):
        form = StyledSetPasswordForm(
            user=self.user,
            data={
                "new_password1": "123456",
                "new_password2": "123456",
            },
        )
        self.assertFalse(form.is_valid())
        self.assertTrue(
            "new_password1" in form.errors or "new_password2" in form.errors
        )

    def test_set_password_valid_complex_succeeds(self):
        form = StyledSetPasswordForm(
            user=self.user,
            data={
                "new_password1": "Pass1@",
                "new_password2": "Pass1@",
            },
        )
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertTrue(user.check_password("Pass1@"))
