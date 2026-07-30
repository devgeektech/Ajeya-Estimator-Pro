from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="list"),
    path("read/", views.MarkAllReadView.as_view(), name="read"),
    path("clear/", views.ClearAllNotificationsView.as_view(), name="clear"),
]
