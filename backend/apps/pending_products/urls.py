from django.urls import path

from . import views

app_name = "pending_products"

urlpatterns = [
    path("", views.PendingProductListView.as_view(), name="list"),
    path("<int:pk>/reject/", views.PendingRejectView.as_view(), name="reject"),
    path("<int:pk>/merge/", views.PendingMergeView.as_view(), name="merge"),
    path("<int:pk>/add/", views.PendingAddView.as_view(), name="add"),
]
