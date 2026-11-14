# Validación rápida: Hermes 1.1.0 — OAuth y protocolo

## Requisitos

Igual que en la spec 001, sobre la rama con 1.0.12 ya fusionada:

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r hermes/requirements.txt
.venv/bin/pip install pytest pytest-asyncio aioresponses httpx
```

## Suite completa

```bash
.venv/bin/pytest
```

Debe pasar entera (principio VII).

## Por lote

| Lote | Comando | Qué demuestra |
|---|---|---|
| Fase 0 | `.venv/bin/pytest tests/test_config_validation.py tests/test_addon_manifest.py tests/test_run_sh_options.py` | Valores por defecto, recortes, antiguo valor por defecto, opciones nuevas (FR-032…FR-035, FR-023, FR-044). |
| A | `.venv/bin/pytest tests/test_cimd.py tests/test_oauth_cimd_flow.py tests/test_oauth_security.py tests/test_oauth_diagnostics.py` | CIMD, SSRF, `iss`, audiencia, compatibilidad DCR (FR-001…FR-031). |
| B | `.venv/bin/pytest tests/test_mcp_protocol.py tests/test_first_byte.py tests/test_middleware_connection.py tests/test_tools_registration.py` | `version`, `title`, `isError`, versiones, `scope` en 401, primer byte (FR-029, FR-036, FR-039…FR-043). |
| C | `.venv/bin/pytest tests/test_log_redact_network.py tests/test_redact_secrets.py` | Redacción de red, loggers estándar, `sv_get_addon_logs` (FR-045…FR-049). |
| Integración | `.venv/bin/pytest tests/test_main_wiring.py tests/test_addon_manifest.py` | Cableado en `__main__` y coherencia del manifiesto (FR-023, FR-039, FR-044, FR-049). |

## Control negativo (principio VII)

Para cada cambio: deshacer solo el código (revertir el hunk), ejecutar el test,
comprobar que falla y anotar «con la guarda quitada caen N tests» en el commit
del lote. Las tareas de control negativo de tasks.md dicen qué deshacer en cada caso.

## Privacidad (principio VIII)

Antes de cada commit, sobre el diff:

```bash
git diff --cached | grep -nEi 'ts\.net|tail[0-9a-f]{4,}|([0-9]{1,3}\.){3}[0-9]{1,3}|auth_password: *[^<"]|@[a-z0-9-]+\.[a-z]{2,}|claude-[a-z0-9]|gpt-|/home/|/Users/'
```

Solo deben aparecer marcadores (`homeassistant.tailXXXX.ts.net`, `<slug>`),
IPs de documentación (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`), `1.1.1.1` (solo en el test de clase `public`), rangos
públicos de RFC (`100.64.0.0/10`, `10.0.0.0/8`…), `127.0.0.1` y la URL pública
del documento CIMD de Claude Code, o falsos positivos explicados.

## Pruebas manuales (instalación de pruebas, no de producción)

1. **Claude Code con CIMD**: `claude mcp add --transport http hermes https://homeassistant.tailXXXX.ts.net/mcp`, autorizar y comprobar en el log `oauth_code_issued` con `client_id` igual a la URL del documento y ningún registro DCR nuevo en `/data/oauth/clients`.
2. **Primer byte**: desde Claude Code sin tocar `MCP_TOOL_TIMEOUT`, `ha_wait_for_event(event_type="hermes_test", timeout_seconds=90)` y, a los 80 s, disparar `hermes_test` con `ha_fire_event` desde otro cliente (con el evento en `fire_event_allowlist`) o desde Herramientas para desarrolladores. Debe volver `matched: true`. Si Claude Code corta a los 60 s, el proxy almacena la respuesta: anotarlo en DOCS.md (FR-037) y en la hoja de ruta.
3. **claude.ai**: conectar un conector nuevo y comprobar que funciona (con DCR o CIMD, según lo que elija claude.ai) y que el `iss` no lo rompe.
4. **Compatibilidad**: actualizar desde 1.0.12 con un conector ya autorizado y comprobar que sigue funcionando sin reautorizar.
5. **Log**: `sv_get_addon_logs(<slug de Hermes>)` no contiene el hostname ni IPs que no sean de loopback; con `log_redact_network: false` sí, y aparece `log_network_redaction_disabled`.
