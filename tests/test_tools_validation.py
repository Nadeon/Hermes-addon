"""Tests de la validación anti path-injection de identificadores y del
guard central de paths del cliente HA."""

import unittest

from hermes import ha
from hermes.tools._validation import (
    InvalidIdentifier,
    validate_identifier,
    validate_slug,
)


class TestValidateSlug(unittest.TestCase):
    def test_accepts_real_addon_slugs(self) -> None:
        for s in ["core_mosquitto", "a0d7b954_tailscale", "local_hermes", "abc123"]:
            self.assertEqual(validate_slug(s), s)

    def test_accepts_backup_hex_slug(self) -> None:
        self.assertEqual(validate_slug("a1b2c3d4"), "a1b2c3d4")

    def test_rejects_traversal_and_slashes(self) -> None:
        for bad in ["../core", "..", "a/../b", "foo/bar", "a/b", "/etc/passwd"]:
            with self.assertRaises(InvalidIdentifier):
                validate_slug(bad)

    def test_rejects_control_and_empty(self) -> None:
        for bad in ["", "   ", "a\nb", "a\x00b", "a b", "a\tb"]:
            with self.assertRaises(InvalidIdentifier):
                validate_slug(bad)


class TestValidateIdentifier(unittest.TestCase):
    def test_accepts_hex_and_uuid_like(self) -> None:
        for s in ["a1b2c3d4e5f6", "01HRXabc-def_ghi", "abcDEF123"]:
            self.assertEqual(validate_identifier(s), s)

    def test_rejects_dot_slash_traversal(self) -> None:
        for bad in ["a.b", "../x", "a/b", "..", "", "a b"]:
            with self.assertRaises(InvalidIdentifier):
                validate_identifier(bad)


class TestRequestPathGuard(unittest.TestCase):
    def test_accepts_normal_paths(self) -> None:
        # No deben lanzar.
        ha._assert_safe_request_path("/addons/core_mosquitto/info")
        ha._assert_safe_request_path("/core/api/states")
        ha._assert_safe_request_path("/backups/a1b2c3d4/info")

    def test_rejects_traversal(self) -> None:
        for bad in ["/addons/../core/restart", "/backups/../../data", "/a/../../b"]:
            with self.assertRaises(ha.HAConnectionError):
                ha._assert_safe_request_path(bad)

    def test_rejects_control_chars(self) -> None:
        with self.assertRaises(ha.HAConnectionError):
            ha._assert_safe_request_path("/addons/x\r\nHost: evil/info")

    def test_rejects_non_absolute(self) -> None:
        with self.assertRaises(ha.HAConnectionError):
            ha._assert_safe_request_path("addons/x/info")


if __name__ == "__main__":
    unittest.main()
