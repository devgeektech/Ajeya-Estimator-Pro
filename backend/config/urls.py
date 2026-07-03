"""Root URL configuration for BOQ_AI."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from common.choices import UserRole


def superadmin_site_permission(request):
    user = request.user
    return (
        user.is_active
        and user.is_staff
        and user.is_superuser
        and user.role == UserRole.SUPERADMIN
    )


admin.site.has_permission = superadmin_site_permission

urlpatterns = [
    path("admin/", admin.site.urls),
    # Send the bare root to the dashboard (which forwards to login when signed
    # out) so visiting "/" never 404s.
    path("", RedirectView.as_view(pattern_name="dashboard:home", permanent=False)),
    path("", include("apps.accounts.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("boqs/", include("apps.boq.urls")),
    path("processing/", include("apps.processing.urls")),
    path("review/", include("apps.review.urls")),
    path("exports/", include("apps.exports.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("pending/", include("apps.pending_products.urls")),
    path("audit/", include("apps.audit.urls")),
    path("users/", include("apps.users.urls")),
    path("database/", include("apps.database_manager.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
