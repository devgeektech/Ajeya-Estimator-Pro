"""Convert legacy ``.xls`` uploads to ``.xlsx`` for BOQ / make-list storage."""
from __future__ import annotations

import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile

from utils.xls_convert import (
    XlsConvertError,
    convert_xls_path_to_xlsx,
    is_xls_filename,
    xls_to_xlsx_filename,
)

from .boq_files import upload_basename

logger = logging.getLogger("boq_ai")


class XlsUploadConversionService:
    """Normalize Excel 97-2003 uploads to Open XML before persist / parse."""

    def maybe_convert(self, uploaded_file: UploadedFile | None):
        """Return ``uploaded_file`` unchanged, or a ``.xlsx`` ContentFile."""
        if not uploaded_file:
            return uploaded_file
        name = upload_basename(uploaded_file)
        if not is_xls_filename(name):
            return uploaded_file

        source_path: str | None = None
        temp_source: str | None = None
        temp_xlsx: str | None = None
        try:
            temp_path = getattr(uploaded_file, "temporary_file_path", None)
            if callable(temp_path):
                source_path = str(temp_path())
            else:
                with NamedTemporaryFile(suffix=".xls", delete=False) as handle:
                    for chunk in uploaded_file.chunks():
                        handle.write(chunk)
                    temp_source = handle.name
                source_path = temp_source

            if not source_path:
                raise XlsConvertError(f"Could not read upload '{name}' for conversion.")

            with NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
                temp_xlsx = handle.name
            convert_xls_path_to_xlsx(source_path, temp_xlsx)

            xlsx_name = xls_to_xlsx_filename(name)
            with open(temp_xlsx, "rb") as handle:
                content = ContentFile(handle.read(), name=xlsx_name)
            logger.info(
                "BOQ upload: converted legacy Excel '%s' to '%s' before save",
                name,
                xlsx_name,
            )
            return content
        except XlsConvertError:
            raise
        except Exception as exc:
            raise XlsConvertError(
                f"Could not convert '{name}' to .xlsx. "
                "Open it in Excel and Save As .xlsx, then upload again."
            ) from exc
        finally:
            if temp_source:
                Path(temp_source).unlink(missing_ok=True)
            if temp_xlsx:
                Path(temp_xlsx).unlink(missing_ok=True)
