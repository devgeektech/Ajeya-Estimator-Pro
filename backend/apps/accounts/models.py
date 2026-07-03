"""Authentication models.

Defines the email-based custom User and roles (docs/PRD.md - User Roles,
docs/DATABASE_ARCHITECTURE.md - User).
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from common.choices import UserRole


class UserManager(BaseUserManager):
    """Manager for the email-based User model."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", UserRole.EXPERT)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", UserRole.SUPERADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """System user. Authentication is performed via email."""

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(
        max_length=20, choices=UserRole.choices, default=UserRole.EXPERT
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    allow_db_access = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # Which Admin created this user (null for the first Developer superuser).
    created_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_users",
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["email"]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.__class__.objects.normalize_email(self.email).lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.email

    @property
    def is_admin(self) -> bool:
        """True when the user has the platform Admin role."""
        return self.role == UserRole.ADMIN

    @property
    def is_superadmin(self) -> bool:
        """True for internal developer superusers."""
        return self.role == UserRole.SUPERADMIN

    @property
    def is_super_admin(self) -> bool:
        """Backward-compat app-admin gate."""
        return self.is_superuser or self.is_admin

    @property
    def is_expert(self) -> bool:
        return self.role == UserRole.EXPERT
