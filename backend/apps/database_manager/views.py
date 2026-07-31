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
from utils.files import stamped_upload_filename

from .forms import DatabaseUploadForm
from .models import (
    DatabaseVersion,
    Labour_master_Output,
    Rate_Master_Output,
)
from .services.activation import repair_duplicate_active_versions
from .services.importer import DatabaseImportService, count_workbook_sheet_rows

logger = logging.getLogger("boq_ai")


class DatabaseVersionListView(LoginRequiredMixin, ListView):
    model = DatabaseVersion
    template_name = "database/version_list.html"
    context_object_name = "versions"

    _SORT_FIELDS = {
        "name": "name",
        "status": "is_active",
        "uploader": "uploaded_by__first_name",
        "uploaded": "uploaded_at",
    }

    def get_queryset(self):
        retained_ids = list(
            DatabaseVersion.objects.order_by("-uploaded_at", "-id").values_list(
                "id", flat=True
            )[:DATABASE_UPLOADS_TO_RETAIN]
        )
        qs = DatabaseVersion.objects.filter(id__in=retained_ids).select_related(
            "uploaded_by"
        )

        sort_key = (self.request.GET.get("sort") or "status").strip().lower()
        direction = (self.request.GET.get("dir") or "desc").strip().lower()
        if sort_key not in self._SORT_FIELDS:
            sort_key = "status"
        if direction not in {"asc", "desc"}:
            direction = "desc"

        if sort_key == "uploader":
            if direction == "desc":
                return qs.order_by(
                    "-uploaded_by__first_name",
                    "-uploaded_by__last_name",
                    "-uploaded_by__email",
                    "-id",
                )
            return qs.order_by(
                "uploaded_by__first_name",
                "uploaded_by__last_name",
                "uploaded_by__email",
                "-id",
            )

        if sort_key == "name":
            if direction == "desc":
                return qs.order_by("-name", "-source_filename", "-version_number", "-id")
            return qs.order_by("name", "source_filename", "version_number", "-id")

        if sort_key == "status":
            if direction == "desc":
                return qs.order_by("-is_active", "-uploaded_at", "-id")
            return qs.order_by("is_active", "uploaded_at", "-id")

        order_field = self._SORT_FIELDS[sort_key]
        if direction == "desc":
            order_field = f"-{order_field}"
        return qs.order_by(order_field, "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        repaired = repair_duplicate_active_versions()
        context["repaired_duplicate_active"] = repaired > 0
        sort_key = (self.request.GET.get("sort") or "status").strip().lower()
        direction = (self.request.GET.get("dir") or "desc").strip().lower()
        if sort_key not in self._SORT_FIELDS:
            sort_key = "status"
        if direction not in {"asc", "desc"}:
            direction = "desc"
        context["search_q"] = (self.request.GET.get("q") or "").strip()
        context["sort"] = sort_key
        context["dir"] = direction
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
            f"database/{stamped_upload_filename(upload.name)}", upload
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
        sheet_stats: list[dict] = []
        if version.file and version.file.name:
            try:
                sheet_stats = count_workbook_sheet_rows(version.file.path)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Failed reading sheet stats for database version %s", version.pk
                )

        rates_count = 0
        labour_count = 0
        if version.is_active:
            rates_count = Rate_Master_Output.objects.filter(
                database_version=version
            ).count()
            labour_count = Labour_master_Output.objects.filter(
                database_version=version
            ).count()

        context = {
            "version": version,
            "sheet_stats": sheet_stats,
            "rates_count": rates_count,
            "labour_count": labour_count,
        }
        return render(request, "database/version_detail.html", context)
