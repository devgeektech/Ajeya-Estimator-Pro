from django.urls import path

from . import views

app_name = "boq"

urlpatterns = [
    path("", views.BOQListView.as_view(), name="list"),
    path("upload/", views.BOQUploadView.as_view(), name="upload"),
    path("<int:pk>/", views.BOQDetailView.as_view(), name="detail"),
]
