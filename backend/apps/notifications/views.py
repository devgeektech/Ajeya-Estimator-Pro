"""Notification views (thin)."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import ListView, View

from apps.notifications.models import Notification
from apps.notifications.services import mark_all_read


class NotificationListView(LoginRequiredMixin, ListView):
    template_name = "notifications/list.html"
    context_object_name = "notifications"
    paginate_by = 30

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


class MarkAllReadView(LoginRequiredMixin, View):
    def post(self, request):
        mark_all_read(request.user)
        return redirect("notifications:list")
