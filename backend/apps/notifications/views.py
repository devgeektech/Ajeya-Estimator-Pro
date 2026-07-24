"""Notification views (thin)."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import ListView, View

from apps.notifications.models import Notification
from apps.notifications.services import (
    clear_all,
    clear_selected,
    mark_all_read,
    mark_selected_read,
)


def _parse_ids(request) -> list[int]:
    ids: list[int] = []
    for value in request.POST.getlist("ids"):
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


class NotificationListView(LoginRequiredMixin, ListView):
    template_name = "notifications/list.html"
    context_object_name = "notifications"
    paginate_by = 30

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


class MarkAllReadView(LoginRequiredMixin, View):
    def post(self, request):
        ids = _parse_ids(request)
        if ids:
            count = mark_selected_read(request.user, ids)
            if count:
                messages.success(
                    request,
                    f"Marked {count} selected notification{'s' if count != 1 else ''} as read.",
                )
            else:
                messages.info(request, "Selected notifications are already read.")
        else:
            count = mark_all_read(request.user)
            if count:
                messages.success(
                    request,
                    f"Marked {count} notification{'s' if count != 1 else ''} as read.",
                )
            else:
                messages.info(request, "No unread notifications.")
        return redirect("notifications:list")


class ClearAllNotificationsView(LoginRequiredMixin, View):
    def post(self, request):
        ids = _parse_ids(request)
        if ids:
            count = clear_selected(request.user, ids)
            if count:
                messages.success(
                    request,
                    f"Cleared {count} selected notification{'s' if count != 1 else ''}.",
                )
            else:
                messages.info(request, "No matching notifications to clear.")
        else:
            count = clear_all(request.user)
            if count:
                messages.success(
                    request,
                    f"Cleared {count} notification{'s' if count != 1 else ''}.",
                )
            else:
                messages.info(request, "No notifications to clear.")
        return redirect("notifications:list")
