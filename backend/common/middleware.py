"""Project-wide response middleware."""
from django.utils.cache import add_never_cache_headers


class NoStoreAuthenticatedMiddleware:
    """Prevent authenticated pages from being restored after logout."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        was_authenticated = (
            hasattr(request, "user") and request.user.is_authenticated
        )
        response = self.get_response(request)
        if was_authenticated:
            add_never_cache_headers(response)
        return response
