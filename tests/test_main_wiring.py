"""Cableado del arranque de la spec 003 (T054).

Cada pieza de la spec (redacción de red del log, ajustes de configuración,
CIMD, servidor MCP con versión, límites efectivos) existe en su módulo y tiene
sus propios tests. Lo que se prueba aquí es lo que solo `__main__` puede
romper: que las opciones LLEGUEN a esas piezas. Sin este cableado todo lo
demás pasa en verde y el add-on se comporta como si las opciones no
existieran.
"""

from __future__ import annotations

import inspect
from unittest import mock

import pytest
from structlog.testing import capture_logs

import hermes.__main__ as main_mod
from hermes import __version__
from hermes.config import RESPONSE_MAX_BYTES_DEFAULT, HermesConfig
from hermes.mcp_server import HermesMCPServer


def _config(**overrides: object) -> HermesConfig:
    base: dict[str, object] = {
        "auth_password": "x" * 20,
        "public_hostname": "homeassistant.tailXXXX.ts.net",
        "supervisor_token": "token-de-prueba",
    }
    base.update(overrides)
    return HermesConfig(**base)  # type: ignore[arg-type]


# ── Log ───────────────────────────────────────────────────────


def test_setup_logging_recibe_las_opciones_de_red() -> None:
    config = _config(log_level="debug", log_redact_network=True)
    with mock.patch.object(main_mod, "setup_logging") as setup:
        main_mod._setup_logging_from_config(config)
    setup.assert_called_once_with(
        "debug",
        redact_network=True,
        public_hostname="homeassistant.tailXXXX.ts.net",
    )


def test_setup_logging_recibe_la_redaccion_desactivada() -> None:
    config = _config(log_redact_network=False)
    with mock.patch.object(main_mod, "setup_logging") as setup:
        main_mod._setup_logging_from_config(config)
    assert setup.call_args.kwargs["redact_network"] is False


def test_redaccion_desactivada_avisa() -> None:
    config = _config(log_redact_network=False)
    with mock.patch.object(main_mod, "setup_logging"), capture_logs() as logs:
        main_mod._setup_logging_from_config(config)
    avisos = [e for e in logs if e["event"] == "log_network_redaction_disabled"]
    assert len(avisos) == 1
    assert avisos[0]["log_level"] == "warning"


def test_redaccion_activa_no_avisa() -> None:
    config = _config(log_redact_network=True)
    with mock.patch.object(main_mod, "setup_logging"), capture_logs() as logs:
        main_mod._setup_logging_from_config(config)
    assert not [e for e in logs if e["event"] == "log_network_redaction_disabled"]


def test_cada_ajuste_de_configuracion_se_registra() -> None:
    config = _config(adjustments=[
        {"option": "response_max_bytes", "configured": 1_048_576,
         "applied": 131_072, "reason": "legacy_default"},
        {"option": "wait_for_event_max_seconds", "configured": 300,
         "applied": 220, "reason": "above_cap"},
    ])
    with mock.patch.object(main_mod, "setup_logging"), capture_logs() as logs:
        main_mod._setup_logging_from_config(config)
    eventos = {e["event"]: e for e in logs}
    legacy = eventos["config_legacy_default_replaced"]
    assert (legacy["option"], legacy["configured"], legacy["applied"]) == (
        "response_max_bytes", 1_048_576, 131_072,
    )
    clamp = eventos["config_value_clamped"]
    assert (clamp["option"], clamp["configured"], clamp["applied"]) == (
        "wait_for_event_max_seconds", 300, 220,
    )


def test_legacy_default_dice_que_valor_poner_si_era_a_proposito() -> None:
    """Quien puso 1 MiB queriendo «lo máximo» debe saber que es 524288."""
    config = _config(adjustments=[
        {"option": "response_max_bytes", "configured": 1_048_576,
         "applied": 131_072, "reason": "legacy_default"},
        {"option": "wait_for_event_max_seconds", "configured": 300,
         "applied": 220, "reason": "above_cap"},
    ])
    with mock.patch.object(main_mod, "setup_logging"), capture_logs() as logs:
        main_mod._setup_logging_from_config(config)
    eventos = {e["event"]: e for e in logs}
    assert "524288" in eventos["config_legacy_default_replaced"]["hint"]
    # Control negativo: el recorte al máximo no lleva esa pista.
    assert "hint" not in eventos["config_value_clamped"]


def test_main_configura_el_log_con_la_funcion_cableada() -> None:
    """`main()` no puede volver a llamar a `setup_logging` sin opciones."""
    fuente = inspect.getsource(main_mod.main)
    assert "_setup_logging_from_config(config)" in fuente
    assert "setup_logging(config.log_level)" not in fuente


# ── OAuth ─────────────────────────────────────────────────────


@pytest.mark.parametrize("cimd", [True, False])
def test_oauth_recibe_cimd_enabled(cimd: bool) -> None:
    config = _config(oauth_cimd_enabled=cimd)
    with mock.patch.object(main_mod, "OAuthServer") as oauth_cls:
        main_mod._build_oauth_server(config)
    assert oauth_cls.call_args.kwargs["cimd_enabled"] is cimd


# ── Servidor MCP y límites ────────────────────────────────────


def test_servidor_mcp_con_version_y_limites_de_la_configuracion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # El entorno dice otra cosa a propósito: si `__main__` dejara de pasar un
    # límite, `register_all_tools` lo leería de aquí y el test lo notaría.
    monkeypatch.setenv("HERMES_RESPONSE_MAX_BYTES", "65536")
    monkeypatch.setenv("HERMES_WAIT_EVENT_MAX_SECONDS", "30")
    config = _config(
        response_max_bytes=200_000,
        wait_for_event_max_seconds=150,
        wait_for_event_max_concurrent=3,
        safety_backup_keep=5,
    )
    with mock.patch("hermes.tools.register_all_tools") as registrar:
        mcp = main_mod._build_mcp(config, object())
    assert isinstance(mcp, HermesMCPServer)
    assert mcp.version == __version__
    kwargs = registrar.call_args.kwargs
    assert kwargs["response_max_bytes"] == 200_000
    assert kwargs["wait_for_event_max_seconds"] == 150
    assert kwargs["wait_for_event_max_concurrent"] == 3
    assert kwargs["safety_backup_keep"] == 5


def test_boot_usa_las_funciones_cableadas() -> None:
    """`_boot` no puede construir OAuth ni MCP por su cuenta, sin opciones."""
    fuente = inspect.getsource(main_mod._boot)
    assert "_build_oauth_server(config)" in fuente
    assert "_build_mcp(config, ha_client)" in fuente
    assert "OAuthServer(" not in fuente
    assert "MCPServer(" not in fuente


def test_ninguna_tool_conserva_el_tope_antiguo_por_defecto() -> None:
    """Los `register` de las tools no pueden volver a 1 MiB por defecto.

    En producción el valor llega siempre de la configuración, pero un
    `register` llamado sin él (tests, una tool nueva) no debe usar el tope que
    la spec 003 retiró por quedar por encima de lo que acepta el cliente.
    """
    from hermes.tools import (
        config_entries,
        filesystem,
        history,
        logbook,
        lovelace,
        registry_device,
        registry_entity,
        statistics,
    )

    for modulo in (config_entries, filesystem, history, logbook, lovelace,
                   registry_device, registry_entity, statistics):
        defecto = inspect.signature(modulo.register).parameters[
            "response_max_bytes"
        ].default
        assert defecto == RESPONSE_MAX_BYTES_DEFAULT, modulo.__name__
