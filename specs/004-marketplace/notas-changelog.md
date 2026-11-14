<!-- Notas para hermes/CHANGELOG.md. La integración final de 1.1.0 las copia
     bajo `## [1.1.0] — AAAA-MM-DD` (la versión y la fecha las pone ella). -->

### Added — Marketplace (antes HACS), de solo lectura

Desde Home Assistant 2026.11, HACS viene integrado en el core como el
Marketplace, con otra API (`marketplace/*`), y las tools `ha_hacs_*` de la
1.0.12 solo podían decir que no lo soportaban. Siete tools nuevas lo leen:

- `ha_marketplace_info`: estado del Marketplace; `warning_accepted` es del
  usuario de HA con el que se conecta Hermes.
- `ha_marketplace_list_repositories`: repositorios, por defecto solo los
  instalados, con `category`, `search` y `limit` (el catálogo completo tiene
  miles).
- `ha_marketplace_get_repository`: detalle de uno, con su entidad `update`.
- `ha_marketplace_list_updates`: instalados con actualización pendiente, según
  el `pending_upgrade` de HA, y cómo instalarla (`update.install`, con
  `confirmation_token`).
- `ha_marketplace_list_releases`: versiones publicadas. Es la única que
  consulta GitHub (a través de HA), y se anuncia de mundo abierto.
- `ha_marketplace_list_critical` y `ha_marketplace_list_removed`:
  repositorios marcados como críticos o retirados del catálogo.

Detectan en cada llamada si hay Marketplace o HACS 2.x (HA ≤ 2026.10) y lo
dicen en `api`; nada se recuerda entre llamadas, porque HA se actualiza sin
reiniciar Hermes. Solo envían una lista cerrada de comandos de lectura: Hermes
no instala, no acepta el aviso de riesgos ni marca nada como visto. Los nombres
y descripciones de los repositorios los escriben terceros: las respuestas lo
avisan y los recortan. `hermes_guide("marketplace")` (o `"hacs"`) lo explica.

### Changed — Las `ha_hacs_*` devuelven la forma nueva

Son alias de las `ha_marketplace_*`: misma respuesta, con `api` y sin
`_disclaimer`, más `_deprecated`. Desaparece el error
`hacs_moved_to_marketplace`. `ha_hacs_list_repositories` acepta
`installed_only` (por defecto `true`: antes devolvía el catálogo entero),
`search` y `limit`. Ya no se anuncian de mundo abierto (`openWorldHint`): leen
lo que HA tiene en memoria y `ha_hacs_get_repository` ya no pide
`repository/info`, que salía a GitHub y quitaba la marca de «nuevo».

### Deprecated — `ha_hacs_info`, `ha_hacs_list_repositories`, `ha_hacs_get_repository` y `ha_hacs_list_updates`

Se retiran en 1.3.0. Usa la `ha_marketplace_*` del mismo nombre; la
descripción de cada alias y su respuesta (`_deprecated`) lo dicen.

### Fixed — El ejemplo de `ha_create_lovelace_resource` usaba una ruta antigua

El ejemplo de `url` pasa a `/local/community/…`, que es donde instala el
Marketplace; `/hacsfiles/` sigue funcionando.
