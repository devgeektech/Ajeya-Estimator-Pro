"""Database management views (thin)."""
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.storage import FileSystemStorage
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import FormView, ListView, View

from apps.audit.services import record
from common.constants import DATABASE_UPLOADS_TO_RETAIN
from common.exceptions import BOQAIError
from common.mixins import DatabaseAccessRequiredMixin
from utils.files import unique_filename

from .forms import DatabaseUploadForm
from .models import (
    DatabaseVersion,
    Labour_Master,
    Rate_Master,
    State_Control_List,
    TOR_Accessories,
    TOR_Labour,
    TOR_Main,
)
from .services.activation import repair_duplicate_active_versions
from .services.importer import DatabaseImportService

logger = logging.getLogger("boq_ai")


class DatabaseVersionListView(LoginRequiredMixin, ListView):
    model = DatabaseVersion
    template_name = "database/version_list.html"
    context_object_name = "versions"

    def get_queryset(self):
        return DatabaseVersion.objects.order_by("-is_active", "-uploaded_at")[
            :DATABASE_UPLOADS_TO_RETAIN
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        repaired = repair_duplicate_active_versions()
        context["repaired_duplicate_active"] = repaired > 0
        return context


class DatabaseUploadView(DatabaseAccessRequiredMixin, FormView):
    form_class = DatabaseUploadForm
    template_name = "database/upload.html"
    success_url = reverse_lazy("database:list")

    def form_valid(self, form):
        name = form.cleaned_data["name"]
        upload = form.cleaned_data["workbook"]
        storage = FileSystemStorage()
        stored_name = storage.save(
            f"database/{unique_filename(upload.name)}", upload
        )
        file_path = storage.path(stored_name)

        try:
            DatabaseImportService(
                file_path=file_path,
                uploaded_by=self.request.user,
                source_filename=upload.name,
                version_name=name,
                stored_name=stored_name,
            ).run()
            record(self.request.user, "database_import", "Workbook", upload.name)
            messages.success(self.request, "Database imported and activated.")
            from apps.notifications.services import notify

            notify(
                self.request.user,
                "Database activated",
                f"'{name or upload.name}' was imported and is now the active database.",
            )
        except BOQAIError as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Database upload failed")
            messages.error(self.request, f"Import failed: {exc}")
            return self.form_invalid(form)

        return super().form_valid(form)


class DatabaseDownloadView(LoginRequiredMixin, View):
    def get(self, request, pk):
        version = get_object_or_404(DatabaseVersion, pk=pk)
        file_name = version.file.name if version.file else None
        if not version.file or not file_name or not version.file.storage.exists(file_name):
            messages.error(request, "File not found for this upload.")
            return redirect("database:list")
        response = FileResponse(
            version.file.open("rb"), as_attachment=True, filename=version.source_filename
        )
        return response


class DatabaseVersionDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        version = get_object_or_404(DatabaseVersion, pk=pk)
        context = {
            "version": version,
            "rates_count": Rate_Master.objects.filter(database_version=version).count(),
            "labour_count": Labour_Master.objects.filter(database_version=version).count(),
            "tor_main_count": TOR_Main.objects.filter(database_version=version).count(),
            "tor_labour_count": TOR_Labour.objects.filter(database_version=version).count(),
            "tor_accessories_count": TOR_Accessories.objects.filter(
                database_version=version
            ).count(),
            "state_control_count": State_Control_List.objects.filter(
                database_version=version
            ).count(),
        }
        return render(request, "database/version_detail.html", context)
