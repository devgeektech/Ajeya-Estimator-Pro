from django.urls import path

from . import views

app_name = "database"

urlpatterns = [
    path("", views.DatabaseVersionListView.as_view(), name="list"),
    path("upload/", views.DatabaseUploadView.as_view(), name="upload"),
    path("import-status/", views.DatabaseImportStatusView.as_view(), name="import_status"),
    path("<int:pk>/", views.DatabaseVersionDetailView.as_view(), name="version_detail"),
    path("<int:pk>/download/", views.DatabaseDownloadView.as_view(), name="download"),
]
