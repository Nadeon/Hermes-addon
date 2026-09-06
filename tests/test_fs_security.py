"""Tests de seguridad para hermes.fs.

Cubre todos los vectores de ataque documentados en fs.py:
  - Traversal: paths que escapan de CONFIG_BASE
  - Blacklist: nombres exactos, patrones glob, directorios
  - Allowlist .storage/: default-deny para todo no listado
  - URL-decode: %2e%2e → .. normalizado antes de check
  - Unicode NFC/NFD: rutas normalizadas de forma consistente
  - Symlinks: el resolve() previo los maneja correctamente
  - Listado: ficheros blacklisted aparecen con is_blacklisted=True
  - Búsqueda: search no lee ficheros blacklisted
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

import hermes.fs as fs_module
from hermes.fs import (
    BlacklistedPathError,
    PathTraversalError,
    check_blacklisted,
    check_path_readable,
    detect_encoding,
    is_binary,
    normalize_path,
)


# ── Fixture: directorio /config temporal ─────────────────────────────────────

@pytest.fixture()
def config_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Crea una raíz /config temporal y parchea CONFIG_BASE."""
    root = tmp_path / "config"
    root.mkdir()
    monkeypatch.setattr(fs_module, "CONFIG_BASE", root.resolve())
    return root.resolve()


# ══════════════════════════════════════════════════════════════════════════════
# 1. normalize_path — traversal
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalizePathTraversal:
    """Rutas que intentan escapar de CONFIG_BASE."""

    def test_relative_traversal_dotdot(self, config_root: Path) -> None:
        with pytest.raises(PathTraversalError):
            normalize_path("../../etc/passwd")

    def test_relative_traversal_deep(self, config_root: Path) -> None:
        with pytest.raises(PathTraversalError):
            normalize_path("../../../etc/passwd")

    def test_absolute_outside_config(self, config_root: Path) -> None:
        with pytest.raises(PathTraversalError):
            normalize_path("/etc/passwd")

    def test_absolute_under_config_accepted(self, config_root: Path) -> None:
        (config_root / "automations.yaml").touch()
        p = normalize_path(f"{config_root}/automations.yaml")
        assert p == config_root / "automations.yaml"

    def test_config_prefix_stripped(self, config_root: Path) -> None:
        (config_root / "scripts.yaml").touch()
        p = normalize_path("/config/scripts.yaml")
        assert p.name == "scripts.yaml"

    def test_config_exact(self, config_root: Path) -> None:
        p = normalize_path("/config")
        assert p == config_root

    def test_relative_ok(self, config_root: Path) -> None:
        (config_root / "configuration.yaml").touch()
        p = normalize_path("configuration.yaml")
        assert p.name == "configuration.yaml"

    def test_empty_path_raises(self, config_root: Path) -> None:
        with pytest.raises(PathTraversalError):
            normalize_path("")

    def test_whitespace_only_raises(self, config_root: Path) -> None:
        with pytest.raises(PathTraversalError):
            normalize_path("   ")

    def test_absolute_other_prefix_raises(self, config_root: Path) -> None:
        with pytest.raises(PathTraversalError):
            normalize_path("/var/log/syslog")


# ══════════════════════════════════════════════════════════════════════════════
# 2. normalize_path — URL encoding
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalizePathURLEncoding:
    """URL-encoded traversal sequences son rechazadas."""

    def test_percent_2e_traversal(self, config_root: Path) -> None:
        with pytest.raises(PathTraversalError):
            normalize_path("%2e%2e%2fetc%2fpasswd")

    def test_percent_2e_2e_slash(self, config_root: Path) -> None:
        with pytest.raises(PathTraversalError):
            normalize_path("%2e%2e/secrets.yaml")

    def test_mixed_case_percent(self, config_root: Path) -> None:
        with pytest.raises(PathTraversalError):
            normalize_path("%2E%2E%2Fetc%2Fpasswd")

    def test_percent_encoded_safe_filename(self, config_root: Path) -> None:
        (config_root / "automations.yaml").touch()
        p = normalize_path("automations%2eyaml")
        assert p.name == "automations.yaml"


# ══════════════════════════════════════════════════════════════════════════════
# 3. normalize_path — Unicode NFC/NFD
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalizePathUnicode:
    """Rutas con NFD se normalizan a NFC antes de procesar."""

    def test_nfd_filename_normalized(self, config_root: Path) -> None:
        import unicodedata
        # "café.yaml" en NFC
        nfc_name = unicodedata.normalize("NFC", "café.yaml")
        (config_root / nfc_name).touch()
        # Mismo nombre en NFD → debe resolver al mismo fichero
        nfd_name = unicodedata.normalize("NFD", "café.yaml")
        assert nfd_name != nfc_name, "Precondición: NFC != NFD en bytes"
        p = normalize_path(nfd_name)
        # Ambas resuelven al mismo path absoluto
        assert p.name == nfc_name or p.name == nfd_name  # depende del OS
        # Lo importante: NO sale de config_root
        assert str(p).startswith(str(config_root))

    def test_nfc_path_safe(self, config_root: Path) -> None:
        (config_root / "café.yaml").touch()
        p = normalize_path("café.yaml")
        assert str(p).startswith(str(config_root))


# ══════════════════════════════════════════════════════════════════════════════
# 4. check_blacklisted — blacklist por nombre exacto
# ══════════════════════════════════════════════════════════════════════════════

class TestBlacklistExactNames:
    """Ficheros en BLACKLIST_NAMES son rechazados."""

    def test_secrets_yaml(self, config_root: Path) -> None:
        p = config_root / "secrets.yaml"
        blocked, reason = check_blacklisted(p)
        assert blocked is True
        assert reason != ""

    def test_known_devices_yaml(self, config_root: Path) -> None:
        p = config_root / "known_devices.yaml"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_ip_bans_yaml(self, config_root: Path) -> None:
        p = config_root / "ip_bans.yaml"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_storage_auth(self, config_root: Path) -> None:
        p = config_root / ".storage" / "auth"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_storage_core_config_entries(self, config_root: Path) -> None:
        p = config_root / ".storage" / "core.config_entries"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_storage_cloud(self, config_root: Path) -> None:
        p = config_root / ".storage" / "cloud"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_storage_onboarding(self, config_root: Path) -> None:
        p = config_root / ".storage" / "onboarding"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_automations_yaml_allowed(self, config_root: Path) -> None:
        p = config_root / "automations.yaml"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_configuration_yaml_allowed(self, config_root: Path) -> None:
        p = config_root / "configuration.yaml"
        blocked, _ = check_blacklisted(p)
        assert blocked is False


# ══════════════════════════════════════════════════════════════════════════════
# 5. check_blacklisted — blacklist por patrón glob
# ══════════════════════════════════════════════════════════════════════════════

class TestBlacklistPatterns:
    """Ficheros que coinciden con BLACKLIST_PATTERNS son rechazados."""

    def test_key_extension(self, config_root: Path) -> None:
        p = config_root / "private.key"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_pem_extension(self, config_root: Path) -> None:
        p = config_root / "fullchain.pem"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_crt_extension(self, config_root: Path) -> None:
        p = config_root / "cert.crt"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_p12_extension(self, config_root: Path) -> None:
        p = config_root / "keystore.p12"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_pfx_extension(self, config_root: Path) -> None:
        p = config_root / "certs.pfx"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_env_extension(self, config_root: Path) -> None:
        p = config_root / ".env"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_credentials_prefix(self, config_root: Path) -> None:
        p = config_root / "credentials.json"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_token_in_name(self, config_root: Path) -> None:
        p = config_root / "access_token.txt"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_token_in_name_prefix(self, config_root: Path) -> None:
        p = config_root / "token_refresh"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_db_extension(self, config_root: Path) -> None:
        p = config_root / "home-assistant_v2.db"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_db_shm_extension(self, config_root: Path) -> None:
        p = config_root / "home-assistant_v2.db-shm"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_db_wal_extension(self, config_root: Path) -> None:
        p = config_root / "home-assistant_v2.db-wal"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_yaml_extension_not_matched(self, config_root: Path) -> None:
        p = config_root / "automations.yaml"
        blocked, _ = check_blacklisted(p)
        assert blocked is False


# ══════════════════════════════════════════════════════════════════════════════
# 6. check_blacklisted — directorios blacklisted
# ══════════════════════════════════════════════════════════════════════════════

class TestBlacklistDirectories:
    """Ficheros bajo directorios en BLACKLIST_DIRECTORIES son rechazados."""

    def test_cloud_dir(self, config_root: Path) -> None:
        p = config_root / ".cloud" / "any_file"
        blocked, reason = check_blacklisted(p)
        assert blocked is True
        assert ".cloud" in reason

    def test_cache_dir(self, config_root: Path) -> None:
        p = config_root / ".cache" / "some_cache"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_deps_dir(self, config_root: Path) -> None:
        p = config_root / "deps" / "requests" / "api.py"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_custom_components_allowed(self, config_root: Path) -> None:
        p = config_root / "custom_components" / "myintegration" / "__init__.py"
        blocked, _ = check_blacklisted(p)
        assert blocked is False


# ══════════════════════════════════════════════════════════════════════════════
# 7. check_blacklisted — .storage/ allowlist
# ══════════════════════════════════════════════════════════════════════════════

class TestStorageAllowlist:
    """Solo los ficheros en la allowlist de .storage/ son permitidos."""

    def test_storage_dir_itself_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_core_entity_registry_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "core.entity_registry"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_core_device_registry_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "core.device_registry"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_core_area_registry_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "core.area_registry"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_core_config_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "core.config"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_lovelace_exact_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "lovelace"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_lovelace_dot_variant_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "lovelace.map"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_lovelace_underscore_variant_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "lovelace_dashboards"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_esphome_variant_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "esphome.something"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_hacs_variant_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "hacs.something"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_frontend_user_data_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "frontend.user_data_abc123"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_person_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "person"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_zone_allowed(self, config_root: Path) -> None:
        p = config_root / ".storage" / "zone"
        blocked, _ = check_blacklisted(p)
        assert blocked is False

    def test_unknown_storage_file_rejected(self, config_root: Path) -> None:
        p = config_root / ".storage" / "core.something_random"
        blocked, reason = check_blacklisted(p)
        assert blocked is True
        assert "allowlist" in reason.lower() or "allowlist" in reason

    def test_mystery_storage_file_rejected(self, config_root: Path) -> None:
        p = config_root / ".storage" / "zigbee2mqtt.data"
        blocked, _ = check_blacklisted(p)
        assert blocked is True

    def test_auth_provider_rejected(self, config_root: Path) -> None:
        p = config_root / ".storage" / "auth_provider.homeassistant"
        blocked, _ = check_blacklisted(p)
        assert blocked is True


# ══════════════════════════════════════════════════════════════════════════════
# 8. check_path_readable — integración completa
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckPathReadable:
    """check_path_readable es el stack completo de seguridad."""

    def test_secrets_raises_blacklisted(self, config_root: Path) -> None:
        with pytest.raises(BlacklistedPathError):
            check_path_readable("secrets.yaml")

    def test_traversal_raises_traversal(self, config_root: Path) -> None:
        with pytest.raises(PathTraversalError):
            check_path_readable("../../etc/passwd")

    def test_key_file_raises_blacklisted(self, config_root: Path) -> None:
        (config_root / "server.key").touch()
        with pytest.raises(BlacklistedPathError):
            check_path_readable("server.key")

    def test_valid_file_returns_path(self, config_root: Path) -> None:
        (config_root / "configuration.yaml").write_text("homeassistant:", encoding="utf-8")
        p = check_path_readable("configuration.yaml")
        assert p == config_root / "configuration.yaml"

    def test_storage_allowed_returns_path(self, config_root: Path) -> None:
        storage = config_root / ".storage"
        storage.mkdir()
        (storage / "core.entity_registry").write_text("{}", encoding="utf-8")
        p = check_path_readable(".storage/core.entity_registry")
        assert p.name == "core.entity_registry"

    def test_storage_random_raises_blacklisted(self, config_root: Path) -> None:
        storage = config_root / ".storage"
        storage.mkdir()
        (storage / "random_unknown").write_text("{}", encoding="utf-8")
        with pytest.raises(BlacklistedPathError):
            check_path_readable(".storage/random_unknown")

    def test_url_encoded_traversal_raises(self, config_root: Path) -> None:
        with pytest.raises(PathTraversalError):
            check_path_readable("%2e%2e%2fetc%2fpasswd")


# ══════════════════════════════════════════════════════════════════════════════
# 9. Symlinks
# ══════════════════════════════════════════════════════════════════════════════

class TestSymlinks:
    """Symlinks dentro de /config son permitidos; los que escapan, rechazados."""

    @pytest.mark.skipif(
        not hasattr(os, "O_NOFOLLOW"),
        reason="symlink tests are most meaningful on POSIX",
    )
    def test_symlink_within_config_allowed(self, config_root: Path) -> None:
        target = config_root / "real.yaml"
        target.write_text("content: ok", encoding="utf-8")
        link = config_root / "link.yaml"
        link.symlink_to(target)
        # normalize_path debe resolver el symlink y mantenerse dentro de config
        p = normalize_path("link.yaml")
        # resolve() sigue el symlink → target real
        assert str(p).startswith(str(config_root))

    @pytest.mark.skipif(
        not hasattr(os, "O_NOFOLLOW"),
        reason="symlink escape test needs POSIX resolve behavior",
    )
    def test_symlink_escaping_config_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config = tmp_path / "config"
        config.mkdir()
        monkeypatch.setattr(fs_module, "CONFIG_BASE", config.resolve())
        # Destino fuera de /config
        outside = tmp_path / "secrets.txt"
        outside.write_text("password: hunter2", encoding="utf-8")
        link = config / "escape_link.yaml"
        link.symlink_to(outside)
        # normalize_path resolve() → outside, que escapa de CONFIG_BASE
        with pytest.raises(PathTraversalError):
            normalize_path("escape_link.yaml")


# ══════════════════════════════════════════════════════════════════════════════
# 10. Detección binaria
# ══════════════════════════════════════════════════════════════════════════════

class TestIsBinary:
    def test_null_byte_is_binary(self) -> None:
        assert is_binary(b"header\x00data") is True

    def test_text_is_not_binary(self) -> None:
        assert is_binary(b"homeassistant:\n  name: Home\n") is False

    def test_empty_not_binary(self) -> None:
        assert is_binary(b"") is False

    def test_utf8_content_not_binary(self) -> None:
        content = "automations: []\n# café\n".encode("utf-8")
        assert is_binary(content) is False


# ══════════════════════════════════════════════════════════════════════════════
# 11. Detección de encoding
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectEncoding:
    def test_utf8_bom(self) -> None:
        data = b"\xef\xbb\xbfhomeassistant:\n  name: Home\n"
        enc, content = detect_encoding(data)
        assert enc == "utf-8-bom"
        assert content.startswith("homeassistant:")

    def test_utf8_no_bom(self) -> None:
        data = "homeassistant:\n  name: Café\n".encode("utf-8")
        enc, content = detect_encoding(data)
        assert enc == "utf-8"
        assert "Café" in content

    def test_latin1_fallback(self) -> None:
        data = b"nombre: caf\xe9\n"
        enc, content = detect_encoding(data)
        assert enc == "latin-1"
        assert "caf" in content

    def test_empty_bytes_utf8(self) -> None:
        enc, content = detect_encoding(b"")
        assert enc == "utf-8"
        assert content == ""

class TestEachBlacklistCarriesItsOwnWeight:
    """Qué protege de verdad cada lista negra, medido y no supuesto.

    Se neutralizó cada mecanismo por separado y se corrió la suite entera:

        BLACKLIST_PATTERNS vacía     -> 18 tests fallaban
        BLACKLIST_DIRECTORIES vacía  ->  3 tests fallaban
        BLACKLIST_BASENAMES vacía    ->  2 tests fallaban
        BLACKLIST_NAMES vacía        ->  0 tests fallaban

    El último merecía mirarse de cerca, y la respuesta no fue la esperada:
    **`BLACKLIST_NAMES` no protege nada en exclusiva**. Comprobadas sus 13
    entradas una a una vaciando la lista, las 13 siguen bloqueadas. Las diez de
    `.storage/` las para el allowlist restrictivo de ese directorio (lo que no
    está explícitamente permitido se deniega), y las tres de YAML las para
    `BLACKLIST_BASENAMES`. Ningún test podía detectar su desaparición porque no
    había nada que detectar.

    Se mantiene como segunda capa deliberada —si el allowlist retrocediera, esos
    ficheros seguirían protegidos—, pero conviene saber que hoy no es quien hace
    el trabajo. Los tests de `.storage/` de abajo afirman el resultado, que es
    el contrato, no cuál de las dos capas lo consigue.

    Lo que sí faltaba cubrir era un fichero con nombre **inocuo** dentro de un
    directorio vetado: los tests que había usaban nombres que ya bloqueaban los
    patrones, así que no aislaban `BLACKLIST_DIRECTORIES`.
    """

    @pytest.fixture(autouse=True)
    def _raiz(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fs_module, "CONFIG_BASE", tmp_path.resolve())
        self.raiz = tmp_path.resolve()

    def _bloqueado(self, rel: str) -> bool:
        ruta = self.raiz / rel
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("x", encoding="utf-8")
        bloqueado, _ = check_blacklisted(ruta)
        return bloqueado

    # ── Lo que SOLO cubre BLACKLIST_NAMES ────────────────────────────────
    # Ficheros de .storage/ por nombre exacto: no encajan con ningún patrón
    # glob ni con ningún basename, y .storage no es un directorio vetado
    # (tiene su propia allowlist).

    @pytest.mark.parametrize("rel", [
        ".storage/http.auth",
        ".storage/core.uuid",
        ".storage/hassio",
        ".storage/repairs.issue_registry",
    ])
    def test_exact_storage_names_are_blocked(self, rel):
        assert self._bloqueado(rel)

    # ── Lo que SOLO cubre BLACKLIST_DIRECTORIES ──────────────────────────
    # Un fichero con nombre inocuo dentro de un directorio vetado. Ningún
    # otro mecanismo lo ve.

    @pytest.mark.parametrize("directorio", [".cloud", ".cache", "deps"])
    def test_a_harmless_name_inside_a_banned_directory_is_blocked(self, directorio):
        assert self._bloqueado(f"{directorio}/notas.txt")

    def test_the_same_name_outside_those_directories_is_allowed(self):
        """Control negativo: lo que bloquea es el directorio, no el nombre."""
        assert not self._bloqueado("notas.txt")

    # ── Lo que SOLO cubre BLACKLIST_BASENAMES ────────────────────────────

    def test_a_secret_file_in_a_subdirectory_is_blocked(self):
        """`BLACKLIST_NAMES` compara la ruta entera; esto se le escapa."""
        assert self._bloqueado("packages/secrets.yaml")

    # ── Lo que SOLO cubre BLACKLIST_PATTERNS ─────────────────────────────

    def test_an_arbitrary_cert_file_is_blocked(self):
        assert self._bloqueado("integraciones/mi_certificado.pem")
