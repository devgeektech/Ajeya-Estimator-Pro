from django.urls import path

from . import views

app_name = "boq"

urlpatterns = [
    path("", views.BOQListView.as_view(), name="list"),
    path("upload/", views.BOQUploadView.as_view(), name="upload"),
    path("<int:pk>/", views.BOQDetailView.as_view(), name="detail"),
    path("<int:pk>/make-list/", views.BOQMakeListView.as_view(), name="make_list"),
    path("<int:pk>/make-list/upload/", views.BOQMakeListUploadView.as_view(), name="make_list_upload"),
]
