from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path(
        "password-reset/",
        views.BOQPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        views.BOQPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        views.BOQPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/complete/",
        views.BOQPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
