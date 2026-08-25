from django.urls import path

from . import views

app_name = "boq"

urlpatterns = [
    path("", views.BOQListView.as_view(), name="list"),
    path("refresh/", views.BOQListRefreshView.as_view(), name="refresh_list"),
    path("upload/", views.BOQUploadView.as_view(), name="upload"),
    path("upload/status/", views.BOQUploadStatusView.as_view(), name="upload_status"),
    path("upload/check-name/", views.BOQNameCheckView.as_view(), name="check_name"),
    path("<int:pk>/", views.BOQDetailView.as_view(), name="detail"),
    path("<int:pk>/extract/", views.BOQExtractView.as_view(), name="extract"),
    path("<int:pk>/rows/<str:row_id>/extract/", views.BOQRowExtractView.as_view(), name="row_extract"),
    path("<int:pk>/extraction/edit/", views.BOQExtractionEditView.as_view(), name="extraction_edit"),
    path("<int:pk>/make-vendor/", views.BOQMakeVendorSelectView.as_view(), name="make_vendor_select"),
    path("<int:pk>/labour/", views.BOQLabourView.as_view(), name="labour"),
    path("<int:pk>/status/", views.BOQAnalysisStatusView.as_view(), name="status"),
    path("<int:pk>/export/", views.BOQExportView.as_view(), name="export"),
]
