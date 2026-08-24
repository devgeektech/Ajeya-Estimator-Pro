"""CSRF origin helper used by production settings."""

from django.test import SimpleTestCase

from common.host_origins import csrf_trusted_origins_from_hosts


class CsrfTrustedOriginsTests(SimpleTestCase):
    def test_http_origins_from_allowed_hosts(self):
        origins = csrf_trusted_origins_from_hosts(
            ["13.205.90.58", "localhost", "127.0.0.1"],
            https=False,
        )
        self.assertEqual(
            origins,
            [
                "http://13.205.90.58",
                "http://localhost",
                "http://127.0.0.1",
            ],
        )

    def test_https_when_ssl_redirect_enabled(self):
        origins = csrf_trusted_origins_from_hosts(["boq.example.com"], https=True)
        self.assertEqual(origins, ["https://boq.example.com"])

    def test_skips_wildcard_and_blanks(self):
        origins = csrf_trusted_origins_from_hosts(["*", "", "  "], https=False)
        self.assertEqual(origins, [])
