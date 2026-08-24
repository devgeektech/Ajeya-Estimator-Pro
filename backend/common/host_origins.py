"""Build CSRF trusted origins from ALLOWED_HOSTS."""


def csrf_trusted_origins_from_hosts(hosts: list[str], *, https: bool) -> list[str]:
    """Return ``scheme://host`` origins Django CSRF will accept.

    Used when ``CSRF_TRUSTED_ORIGINS`` is not set in the environment so POSTs
    work on the EC2 public IP (HTTP) or a later HTTPS domain.
    """
    scheme = "https" if https else "http"
    origins: list[str] = []
    seen: set[str] = set()
    for raw in hosts:
        host = str(raw or "").strip()
        if not host or host == "*":
            continue
        if host.startswith("."):
            origin = f"{scheme}://*{host}"
        else:
            origin = f"{scheme}://{host}"
        if origin not in seen:
            seen.add(origin)
            origins.append(origin)
    return origins
