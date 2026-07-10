"""Authentication views (thin)."""
from typing import cast

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views import View

from .forms import (
    EmailLoginForm,
    ProfileForm,
    RegisteredEmailPasswordResetForm,
    StyledPasswordChangeForm,
)
from .models import User
from .services import record_login, record_logout


@method_decorator(never_cache, name="dispatch")
class LoginView(View):
    template_name = "accounts/login.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard:home")
        return render(request, self.template_name, {"form": EmailLoginForm()})

    def post(self, request):
        form = EmailLoginForm(request.POST, request=request)
        if form.is_valid():
            user = cast(User, form.get_user())
            if user is None:
                return render(request, self.template_name, {"form": form})
            login(request, user)
            record_login(user)
            messages.success(request, f"Welcome back, {user.full_name}.")
            return redirect("dashboard:home")
        return render(request, self.template_name, {"form": form})


@method_decorator(never_cache, name="dispatch")
class LogoutView(View):
    def post(self, request):
        record_logout(request.user)
        logout(request)
        messages.info(request, "You have been logged out.")
        return redirect("accounts:login")


@method_decorator(never_cache, name="dispatch")
class ProfileView(LoginRequiredMixin, View):
    template_name = "accounts/profile.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "profile_form": ProfileForm(instance=request.user),
                "password_form": StyledPasswordChangeForm(request.user),
            },
        )

    def post(self, request):
        profile_form = ProfileForm(instance=request.user)
        password_form = StyledPasswordChangeForm(request.user)

        if "profile_submit" in request.POST:
            profile_form = ProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile updated successfully.")
                return redirect("accounts:profile")

        if "password_submit" in request.POST:
            password_form = StyledPasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password updated successfully.")
                return redirect("accounts:profile")

        return render(
            request,
            self.template_name,
            {"profile_form": profile_form, "password_form": password_form},
        )


@method_decorator(never_cache, name="dispatch")
class BOQPasswordResetView(PasswordResetView):
    form_class = RegisteredEmailPasswordResetForm
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/password_reset_email.html"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class BOQPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class BOQPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class BOQPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"
