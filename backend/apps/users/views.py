"""User management views, restricted to Admin role (thin)."""
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View
from django.shortcuts import get_object_or_404, redirect

from apps.accounts.models import User
from common.choices import UserRole
from common.mixins import SuperAdminRequiredMixin

from .forms import UserCreateForm, UserEditForm


def platform_users():
    """Users managed by the app UI; developer superusers stay internal."""
    return User.objects.filter(is_superuser=False)


class UserListView(SuperAdminRequiredMixin, ListView):
    model = User
    template_name = "users/user_list.html"
    context_object_name = "users"
    paginate_by = 25

    def get_queryset(self):
        return platform_users().exclude(pk=self.request.user.pk)


class UserCreateView(SuperAdminRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = "users/user_form.html"
    success_url = reverse_lazy("users:list")

    def form_valid(self, form):
        user = form.save(commit=False)
        user.created_by = self.request.user
        user.save()
        messages.success(self.request, f"User '{user.email}' created successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Create User"
        return ctx


class UserEditView(SuperAdminRequiredMixin, UpdateView):
    model = User
    form_class = UserEditForm
    template_name = "users/user_form.html"
    success_url = reverse_lazy("users:list")

    def get_queryset(self):
        return platform_users().exclude(pk=self.request.user.pk)

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


class UserToggleActiveView(SuperAdminRequiredMixin, View):
    """Activate / deactivate a user (Super Admin cannot deactivate self)."""

    def post(self, request, pk):
        user = get_object_or_404(platform_users().exclude(pk=request.user.pk), pk=pk)
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        state = "activated" if user.is_active else "deactivated"
        messages.success(request, f"User {state}.")
        return redirect("users:list")


class UserToggleDbAccessView(SuperAdminRequiredMixin, View):
    """Grant / revoke DB access for a user."""

    def post(self, request, pk):
        user = get_object_or_404(platform_users().exclude(pk=request.user.pk), pk=pk)
        if user.role == UserRole.ADMIN:
            if not user.allow_db_access:
                user.allow_db_access = True
                user.save(update_fields=["allow_db_access"])
            messages.info(request, "Admin users always have DB access.")
            return redirect("users:list")
        user.allow_db_access = not getattr(user, 'allow_db_access', False)
        user.save(update_fields=["allow_db_access"])
        state = "granted DB access" if user.allow_db_access else "revoked DB access"
        messages.success(request, f"User {state}.")
        return redirect("users:list")


class UserDeleteView(SuperAdminRequiredMixin, View):
    """Delete a user account (Admin cannot delete self)."""

    def post(self, request, pk):
        user = get_object_or_404(platform_users().exclude(pk=request.user.pk), pk=pk)
        email = user.email
        user.delete()
        messages.success(request, f"User '{email}' deleted successfully.")
        return redirect("users:list")
