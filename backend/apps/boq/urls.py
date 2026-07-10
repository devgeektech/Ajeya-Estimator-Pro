from django.urls import path

from . import views

app_name = "boq"

urlpatterns = [
    path("upload/", views.BOQUploadView.as_view(), name="upload"),
]
