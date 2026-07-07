from django.urls import path

from . import views

app_name = "exports"

urlpatterns = [
    path("boq/<int:pk>/generate/", views.GenerateExportView.as_view(), name="generate"),
    path(
        "boq/<int:pk>/download/<str:kind>/",
        views.DownloadExportView.as_view(),
        name="download",
    ),
]
