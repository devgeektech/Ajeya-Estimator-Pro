"""Small BOQ file helpers shared across services."""


def upload_basename(uploaded_file) -> str:
    name = getattr(uploaded_file, "name", None) or ""
    return name.rsplit("/", 1)[-1]
