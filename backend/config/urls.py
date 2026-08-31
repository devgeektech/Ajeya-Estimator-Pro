"""Root URL configuration for BOQ_AI."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from common.admin_site import lock_django_admin_to_superadmin

lock_django_admin_to_superadmin()

urlpatterns = [
    path("admin/", admin.site.urls),
    # Send the bare root to the dashboard (which forwards to login when signed
    # out) so visiting "/" never 404s.
    path("", RedirectView.as_view(pattern_name="dashboard:home", permanent=False)),
    path("", include("apps.accounts.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("boqs/", include("apps.boq.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("audit/", include("apps.audit.urls")),
    path("users/", include("apps.users.urls")),
    path("database/", include("apps.database_manager.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
