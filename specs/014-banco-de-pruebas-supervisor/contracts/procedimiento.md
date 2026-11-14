# Contrato: procedimiento del banco del Supervisor (spec 014, FR-001, FR-006)

`docs/BANCO-SUPERVISOR.md`, en español, con marcadores genéricos
(`<ip-de-la-vm>`, `haos-prueba.tailXXXX.ts.net`, `<slug>`, `192.0.2.x`) y sin
ningún dato real (principio VIII). Los comandos van en bloques de código
dentro del texto; no hay scripts versionados (research R-3).

## Encabezados obligatorios (los comprueba `test_procedimiento_con_sus_secciones`)

Exactamente estos `##`, en este orden:

1. `## Para qué sirve y qué no`
   - Qué se prueba solo aquí (reinicios, apagados, restauraciones,
     desinstalaciones, cambio de rol) y por qué no en la instalación real.
   - Que nada de esto lo ejecuta el CI ni lo automatiza el proyecto, y que la
     VM en un runner con KVM es una duda abierta (D-06).
2. `## Versiones`
   - HAOS de la imagen oficial; Core 2026.11.1 fijado con `ha core update
     --version 2026.11.1`; el Supervisor no se puede fijar (fuera del modo de
     desarrollo, `POST /supervisor/update` ignora `version`): se usa el que
     haya, con la actualización automática activada, y su versión real se
     anota en la nota de cada fila de la matriz. Cómo comprobarlo (`ha
     supervisor info`, `ha core info`).
   - Por qué no se desactiva la actualización automática (con un Supervisor
     pendiente de actualizar, `supervisor_updated` bloquea add-ons, la tienda
     y `ha core update`) y, solo en la VM, cómo ignorar esa condición con
     `POST /jobs/options` y cómo deshacerlo.
3. `## Crear la VM`
   - Recursos mínimos (2 vCPU, 4 GB de RAM, 32 GB de disco), UEFI, red
     aislada o NAT; Hyper-V (`vhdx`, generación 2, sin arranque seguro y
     diciendo por qué: el cargador de HAOS no está firmado con las claves de
     la plantilla; solo afecta a esa VM) y
     QEMU/libvirt (`qcow2`); remisión a la guía oficial para VMware y
     VirtualBox.
   - Onboarding con un usuario de prueba; nada de la instalación real (ni
     backups, ni configuración, ni tokens).
4. `## Instantáneas`
   - Antes de cada tanda y antes de cada prueba destructiva; cómo restaurar
     (Hyper-V: `Checkpoint-VM`/`Restore-VMCheckpoint`; libvirt: con la VM
     apagada, copiar el `qcow2` y el `nvram` y devolverlos para restaurar,
     porque libvirt no admite instantáneas internas con firmware UEFI).
5. `## Instalar Hermes como add-on local`
   - Copiar `hermes/` a la carpeta de apps locales (`/addons` o `/local_apps`
     en el add-on de terminal y SSH), quitar la línea `image:` de
     `config.yaml`, recargar la tienda e instalar `local_hermes` (se construye
     desde el `Dockerfile`; tarda).
   - Opciones de prueba: `auth_password` generada para la ocasión (por
     ejemplo con `python -c "import secrets; print(secrets.token_urlsafe(24))"`)
     y guardada fuera del repositorio; `public_hostname` del TLS de la VM;
     `network_mode` según el TLS elegido.
6. `## Conectar un cliente MCP`
   - TLS delante como en producción, porque el emisor OAuth es
     `https://<public_hostname>`. Por defecto, sin exponer la VM a internet:
     `tailscale serve` con el add-on de Tailscale en la VM, un nombre de
     máquina propio y un tailnet de pruebas aparte del de la instalación real
     (o un proxy local con certificado de confianza). Funnel solo para
     clientes en la nube, con el aviso de que publica un Hermes con rol
     `admin` y cómo cerrarlo (`tailscale funnel --https=8443 off`).
   - Cliente: Claude Code u otro cliente MCP; comprobar `ping` y
     `sv_get_supervisor_info` antes de empezar.
7. `## Tandas de pruebas`
   - Tanda 1, sin interrupción: lecturas, `sv_check_core_config`,
     `sv_create_backup_full`, `sv_create_backup_partial`,
     `sv_create_safety_backup`, `sv_get_job_status`, `sv_set_addon_options`
     (sobre un add-on de prueba), `fs_write_file`, `fs_move_file`,
     `fs_delete_file`, `fs_restore_file_backup`, `fs_set_secret`,
     `sv_dismiss_resolution_issue` y `sv_dismiss_resolution_suggestion` (con
     un aviso provocado).
   - Tanda 2, add-ons, con instantánea: `sv_install_addon`, `sv_start_addon`,
     `sv_stop_addon`, `sv_restart_addon`, `sv_update_addon` (con una versión
     anterior instalada) y `sv_uninstall_addon`, siempre sobre un add-on de
     prueba de la tienda oficial; y, sobre `local_hermes`, solo la vista
     previa de `sv_stop_addon` (tiene que llevar el aviso de autoprotección) y
     `sv_update_addon` (tiene que rechazarse antes de llamar al Supervisor,
     spec 009, CAP-021), sin confirmar.
   - Tanda 3, interrupciones, una por instantánea: `sv_restart_core`,
     `sv_reboot_host`, `sv_delete_backup`, `sv_restore_backup_partial`,
     `sv_restore_backup_full`.
   - Para cada tool: la vista previa (que no cambie nada y que describa
     exactamente el efecto), la ejecución con el token, el efecto comprobado
     fuera de Hermes (interfaz de HA o `ha` en la terminal) y el log de Hermes
     sin secretos.
   - Las tools `sv_*` nuevas del programa: misma pauta, en la tanda que les
     toque por su efecto; cada sub-feature que las añada añade aquí su línea.
8. `## Probar hassio_role: manager`
   - Cambiar `hassio_role: manager` en la copia local, reconstruir e instalar;
     comprobar el arranque, `sv_get_addon_options` y las opciones que
     devuelve `sv_get_addon` sobre otro add-on, y todas las `sv_*` de la
     matriz; criterio: ningún 403 nuevo en el log del Supervisor
     (`ha supervisor logs`) ni en las respuestas.
   - Que el rol del add-on publicado no cambia sin la decisión D-02.
9. `## Pruebas manuales que se pueden hacer en la VM`
   - Las de CAP-035 con entorno VM (research R-5): `fs_write_file` sin
     documento y la limpieza de `/data/pending_confirmations`; la clave
     `homeassistant` con Core anterior a 2024.10; `sv_get_resolution` con
     avisos reales; trazas de un script.
10. `## Anotar el resultado`
    - Cambiar `pendiente` por `ok` o `falla` en la matriz de la hoja de ruta,
      con la versión de Hermes, la fecha y, si falla, la causa; marcar la
      casilla manual. Nada de datos de la VM (IPs, nombres) en la nota.
11. `## Limpiar`
    - Borrar la VM o volver a la instantánea inicial; cerrar Funnel si se
      usó y quitar el nodo del tailnet de pruebas; no conservar backups de la VM.
