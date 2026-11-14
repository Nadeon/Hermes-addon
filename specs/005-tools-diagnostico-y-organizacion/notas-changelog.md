<!-- Notas para hermes/CHANGELOG.md, solo de los bloques A y B de la spec 005.
     Las del bloque C (backups de HA, resolución del Supervisor y
     `safety_backup_keep`) las añade quien lo integre. La integración final de
     1.1.0 las copia bajo `## [1.1.0] — AAAA-MM-DD`. -->

### Added — Plantas, etiquetas y categorías

Hermes ya gestionaba entidades, dispositivos y áreas; faltaban las otras tres
formas que tiene HA de organizar la casa. Doce tools nuevas:

- Plantas: `ha_list_floors`, `ha_create_floor`, `ha_update_floor`,
  `ha_delete_floor`.
- Etiquetas: `ha_list_labels`, `ha_create_label`, `ha_update_label`,
  `ha_delete_label`.
- Categorías, por ámbito (automation, script, scene o helpers):
  `ha_list_categories`, `ha_create_category`, `ha_update_category`,
  `ha_delete_category`.

Crear no pide confirmación (no se pierde nada). Editar y borrar sí. La vista
previa de un borrado separa lo que HA limpia solo (áreas, dispositivos o
entidades que pierden la planta, la etiqueta o la categoría) de lo que no
edita: automatizaciones, scripts y escenas que la usan como objetivo y que
dejarán de encontrar nada sin avisar. Si alguna lectura falla, no hay token.

### Added — Diagnóstico: Repairs, trazas y relaciones

Para responder «¿por qué no funciona?» sin abrir la interfaz:

- `ha_list_repairs` y `ha_ignore_repair`: los avisos del panel Reparaciones,
  ordenados por gravedad y con los datos internos redactados. Ignorar pide
  confirmación, porque oculta un aviso que puede anunciar una rotura futura;
  no arregla nada y se deshace con `ignore=false`.
- `ha_list_traces` y `ha_get_trace`: las últimas ejecuciones de una
  automatización o un script, con el `entity_id` de siempre. El detalle sale
  resumido por defecto, con las variables redactadas, y nunca pasa de 64 KiB
  ni de `response_max_bytes`.
- `ha_search_related`: qué usa algo y qué lo usa, para saber qué se romperá
  antes de renombrar o borrar.

`hermes_guide("diagnostics")` (o `"repairs"`, `"traces"`) lo explica, y
`hermes_guide("registries")` incluye plantas, etiquetas y categorías.
