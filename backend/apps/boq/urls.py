from django.urls import path

from . import views

app_name = "boq"

# Row-level re-analyse / re-match: row_extract, row_match

urlpatterns = [
    path("", views.BOQListView.as_view(), name="list"),
    path("upload/", views.BOQUploadView.as_view(), name="upload"),
    path("<int:pk>/", views.BOQDetailView.as_view(), name="detail"),
    path("<int:pk>/extract/", views.BOQExtractView.as_view(), name="extract"),
    path("<int:pk>/rows/<str:row_id>/extract/", views.BOQRowExtractView.as_view(), name="row_extract"),
    path("<int:pk>/rows/<str:row_id>/match/", views.BOQRowMatchView.as_view(), name="row_match"),
    path("<int:pk>/extraction/edit/", views.BOQExtractionEditView.as_view(), name="extraction_edit"),
    path("<int:pk>/process/", views.BOQProcessView.as_view(), name="process"),
    path("<int:pk>/match/", views.BOQMatchView.as_view(), name="match"),
    path("<int:pk>/match-results/", views.BOQMatchResultsView.as_view(), name="match_results"),
    path("<int:pk>/status/", views.BOQAnalysisStatusView.as_view(), name="status"),
    path("<int:pk>/confirm/", views.BOQConfirmView.as_view(), name="confirm"),
    path("<int:pk>/export/", views.BOQExportView.as_view(), name="export"),
]
