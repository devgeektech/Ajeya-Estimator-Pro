"""Lock Django admin to platform Superadmin only.

Anonymous users are sent to the app login (not Django's admin login page).
Authenticated non-Superadmins get 404 so /admin/ appears disabled.
"""
from functools import update_wrapper

from django.conf import settings
from django.contrib import admin
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from common.choices import UserRole


def user_may_access_django_admin(user) -> bool:
    """True only for an active Superadmin with Django staff + superuser flags."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(
        user.is_active
        and user.is_staff
        and user.is_superuser
        and getattr(user, "role", None) == UserRole.SUPERADMIN
    )


def lock_django_admin_to_superadmin(site=None):
    """Patch the given AdminSite (default: django.contrib.admin.site)."""
    site = site or admin.site

    def has_permission(request):
        return user_may_access_django_admin(request.user)

    @never_cache
    def login(request, extra_context=None):
        if user_may_access_django_admin(request.user):
            return redirect("admin:index")
        if request.user.is_authenticated:
            raise Http404()
        login_url = reverse(settings.LOGIN_URL)
        next_url = request.GET.get("next") or request.get_full_path()
        return redirect(f"{login_url}?next={next_url}")

    def admin_view(view, cacheable=False):
        def inner(request, *args, **kwargs):
            if not has_permission(request):
                if request.user.is_authenticated:
                    raise Http404()
                login_url = reverse(settings.LOGIN_URL)
                return redirect(f"{login_url}?next={request.get_full_path()}")
            return view(request, *args, **kwargs)

        if not cacheable:
            inner = never_cache(inner)
        if not getattr(view, "csrf_exempt", False):
            return update_wrapper(csrf_protect(inner), view)
        return update_wrapper(inner, view)

    site.has_permission = has_permission
    site.login = login
    site.admin_view = admin_view
