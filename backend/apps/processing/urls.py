from django.urls import path

from . import views

app_name = "processing"

urlpatterns = [
    path("", views.ProcessingListView.as_view(), name="list"),
    path("boq/<int:pk>/start/", views.StartProcessingView.as_view(), name="start"),
    path("run/<int:pk>/status/", views.RunStatusView.as_view(), name="status"),
]
