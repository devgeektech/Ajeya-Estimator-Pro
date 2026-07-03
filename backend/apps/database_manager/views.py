"""Database management views (Super Admin only, thin)."""
import logging

from django.contrib import messages
from django.core.files.storage import FileSystemStorage
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import FormView, ListView, View

from common.exceptions import BOQAIError
from django.contrib.auth.mixins import LoginRequiredMixin
from common.mixins import DatabaseAccessRequiredMixin
from utils.files import unique_filename

from .forms import DatabaseUploadForm
from .models import DatabaseVersion
from .services.rollback import DatabaseRollbackService

logger = logging.getLogger("boq_ai")


class DatabaseVersionListView(LoginRequiredMixin, ListView):
    model = DatabaseVersion
    template_name = "database/version_list.html"
    context_object_name = "versions"

    def get_queryset(self):
        return DatabaseVersion.objects.order_by("-is_active", "-uploaded_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        versions = list(context["versions"])
        rollback_count = 0
        for v in versions:
            if not v.is_active:
                if rollback_count < 2:
                    v.can_rollback = True
                    rollback_count += 1
                else:
                    v.can_rollback = False
            else:
                v.can_rollback = False
        context["versions"] = versions
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

        from tasks.import_database import import_database_task

        try:
            result = import_database_task.delay(
                file_path, self.request.user.pk, upload.name, name, stored_name
            )
            # In local/eager mode the result is available immediately and
            # exceptions propagate; in production this returns at once.
            if getattr(result, "successful", None) and result.successful():
                from apps.audit.services import record

                record(self.request.user, "database_import", "Workbook", upload.name)
                messages.success(self.request, "Database imported and activated.")
            else:
                messages.info(
                    self.request, "Database import has been queued for processing."
                )
        except BOQAIError as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Database upload failed")
            messages.error(self.request, f"Import failed: {exc}")
            return self.form_invalid(form)

        return super().form_valid(form)


class DatabaseRollbackView(DatabaseAccessRequiredMixin, View):
    def post(self, request, pk):
        version = get_object_or_404(DatabaseVersion, pk=pk)
        try:
            DatabaseRollbackService(version).run()
            from apps.audit.services import record

            record(request.user, "database_rollback", "DatabaseVersion", version.pk)
            messages.success(
                request, f"Rolled back to database v{version.version_number}."
            )
        except BOQAIError as exc:
            messages.error(request, str(exc))
        return redirect("database:list")


class DatabaseDownloadView(LoginRequiredMixin, View):
    def get(self, request, pk):
        from django.http import FileResponse, Http404

        version = get_object_or_404(DatabaseVersion, pk=pk)
        if not version.file or not version.file.storage.exists(version.file.name):
            messages.error(request, "File not found for this version.")
            return redirect("database:list")
        
        response = FileResponse(version.file.open('rb'), as_attachment=True, filename=version.source_filename)
        return response


class DatabaseVersionDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        from django.shortcuts import render
        version = get_object_or_404(DatabaseVersion, pk=pk)
        from .models import StateControl
        context = {
            "version": version,
            "rates_count": version.rates.count(),
            "labour_count": version.labour_rates.count(),
            "tor_main_count": version.tor_main.count(),
            "tor_labour_count": version.tor_labour.count(),
            "tor_accessories_count": version.tor_accessories.count(),
            "state_control_count": StateControl.objects.count(),
        }
        return render(request, "database/version_detail.html", context)
