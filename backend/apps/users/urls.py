from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("", views.UserListView.as_view(), name="list"),
    path("create/", views.UserCreateView.as_view(), name="create"),
    path("<int:pk>/edit/", views.UserEditView.as_view(), name="edit"),
    path("<int:pk>/toggle-active/", views.UserToggleActiveView.as_view(), name="toggle_active"),
    path("<int:pk>/toggle-db-access/", views.UserToggleDbAccessView.as_view(), name="toggle_db_access"),
    path("<int:pk>/delete/", views.UserDeleteView.as_view(), name="delete"),
]
