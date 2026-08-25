"""User management views (thin).

Admins manage Experts they created. Only Superadmin may create/edit/delete
peer Admins.
"""
from django.contrib import messages
from django.db.models import QuerySet
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View
from django.shortcuts import get_object_or_404, redirect

from apps.accounts.models import User
from common.choices import UserRole
from common.mixins import AdminRequiredMixin

from .forms import UserCreateForm, UserEditForm


def platform_users() -> QuerySet[User]:
    """Users managed by the app UI; developer superusers stay internal."""
    return User.objects.filter(is_superuser=False)


def users_managed_by(actor: User) -> QuerySet[User]:
    """Users the actor may list and manage.

    - Superadmin / Django superuser: every platform user.
    - Admin: Experts they created only (not peer Admins or other teams).
    """
    qs = platform_users()
    if getattr(actor, "is_superuser", False) or getattr(actor, "is_superadmin", False):
        return qs
    if getattr(actor, "is_admin", False):
        return qs.filter(role=UserRole.EXPERT, created_by=actor)
    return qs.none()


class UserListView(AdminRequiredMixin, ListView):
    model = User
    template_name = "users/user_list.html"
    context_object_name = "users"
    paginate_by = 25

    def get_queryset(self):
        return users_managed_by(self.request.user).exclude(pk=self.request.user.pk)


class UserCreateView(AdminRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = "users/user_form.html"
    success_url = reverse_lazy("users:list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        user = form.save(commit=False)
        user.created_by = self.request.user
        # Non-superadmin Admins may only create Experts.
        if (
            not getattr(self.request.user, "is_superuser", False)
            and not getattr(self.request.user, "is_superadmin", False)
            and user.role == UserRole.ADMIN
        ):
            messages.error(self.request, "Only Superadmin can create Admin users.")
            return self.form_invalid(form)
        user.save()
        messages.success(self.request, f"User '{user.email}' created successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Create User"
        return ctx


class UserEditView(AdminRequiredMixin, UpdateView):
    model = User
    form_class = UserEditForm
    template_name = "users/user_form.html"
    success_url = reverse_lazy("users:list")

    def get_queryset(self):
        return users_managed_by(self.request.user).exclude(pk=self.request.user.pk)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "User updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Edit User"
        return ctx


class UserToggleActiveView(AdminRequiredMixin, View):
    """Activate / deactivate a managed user (cannot toggle self)."""

    def post(self, request, pk):
        user = get_object_or_404(
            users_managed_by(request.user).exclude(pk=request.user.pk), pk=pk
        )
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        state = "activated" if user.is_active else "deactivated"
        messages.success(request, f"User {state}.")
        return redirect("users:list")


class UserToggleDbAccessView(AdminRequiredMixin, View):
    """Grant / revoke DB upload access for a managed Expert."""

    def post(self, request, pk):
        user = get_object_or_404(
            users_managed_by(request.user).exclude(pk=request.user.pk), pk=pk
        )
        if user.role == UserRole.ADMIN:
            if not user.allow_db_access:
                user.allow_db_access = True
                user.save(update_fields=["allow_db_access"])
            messages.info(request, "Admin users always have DB access.")
            return redirect("users:list")
        user.allow_db_access = not getattr(user, "allow_db_access", False)
        user.save(update_fields=["allow_db_access"])
        state = "granted DB access" if user.allow_db_access else "revoked DB access"
        messages.success(request, f"User {state}.")
        return redirect("users:list")


class UserDeleteView(AdminRequiredMixin, View):
    """Delete a managed user (cannot delete self)."""

    def post(self, request, pk):
        user = get_object_or_404(
            users_managed_by(request.user).exclude(pk=request.user.pk), pk=pk
        )
        email = user.email
        user.delete()
        messages.success(request, f"User '{email}' deleted successfully.")
        return redirect("users:list")
