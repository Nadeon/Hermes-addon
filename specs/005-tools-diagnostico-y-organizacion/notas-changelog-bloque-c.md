# Notas de CHANGELOG — bloque C (spec 005)

Para fundir en `hermes/CHANGELOG.md` bajo `## [1.1.0]` en el bloque de
integración (T069). No se sube la versión.

### Added

- **Centro de resolución del Supervisor.** `sv_get_resolution` devuelve, de
  solo lectura, los motivos de instalación no soportada o no saludable, los
  issues, las sugerencias y los checks del Supervisor, con las referencias
  redactadas. `sv_dismiss_resolution_issue` y
  `sv_dismiss_resolution_suggestion` los descartan con `confirmation_token`;
  la vista previa dice qué se descarta y que puede volver si la condición
  persiste. Hermes **nunca aplica** sugerencias del Supervisor (algunas borran
  backups o reinician el host); un test lo vigila.
- **Backups de Home Assistant.** `ha_list_backups`, `ha_get_backup` y
  `ha_get_backup_config` (HA 2025.1 o posterior) leen la integración `backup`
  de HA, que incluye todas sus ubicaciones (local, red, nube). Las respuestas
  se construyen por lista blanca: nunca salen la contraseña de cifrado de los
  backups automáticos (solo `password_set`), el identificador de la
  instalación ni campos nuevos que HA añada; los errores de los agentes se
  devuelven recortados y sin secretos, IPs ni hosts.
- **Retención de los safety backups** (opción `safety_backup_keep`, 0–50, 3
  por defecto; solo actúa con `safety_backup_enabled`). Tras cada safety
  backup automático correcto, Hermes conserva los `safety_backup_keep` más
  recientes y borra el resto (como mucho 5 por vez). Solo borra backups que él
  mismo anotó al crearlos y cuyo identificador confirmó; nunca uno ajeno
  aunque se llame `hermes-safety-…`, ni uno protegido con contraseña,
  parcial, copiado a otra ubicación o con fecha ilegible, ni el que acaba de
  crear. Ante cualquier duda no borra nada, y un fallo de la poda nunca
  bloquea la escritura en `/config`. `0` la desactiva.

### Changed

- `sv_create_safety_backup` anota sus backups como safety backups de Hermes:
  entran en la retención, que se aplica en el siguiente safety backup
  automático correcto. La tool sigue sin borrar nada.

### Notas

- Los safety backups creados antes de 1.1.0 no están anotados y no se podan
  solos: se borran a mano con `sv_delete_backup`.
