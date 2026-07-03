from django.urls import path

from . import views

app_name = "review"

urlpatterns = [
    path("boq/<int:pk>/", views.ReviewView.as_view(), name="detail"),
    path("boq/<int:pk>/start/", views.StartReviewView.as_view(), name="start"),
    path("boq/<int:pk>/approve/", views.ApproveView.as_view(), name="approve"),
    path("boq/<int:pk>/revise/", views.ReviseView.as_view(), name="revise"),
    path("item/<int:item_id>/apply/", views.ApplyReviewView.as_view(), name="apply"),
]
