# Banco de pruebas del Supervisor

Procedimiento para probar en una máquina virtual con Home Assistant OS las
tools de Hermes que el banco de Core no puede ejecutar: las del Supervisor
(`sv_*`) y las que escriben en `/config` (`fs_*`). Es la parte del Supervisor
del banco de pruebas de la 1.2.0 (spec 014). El resultado de cada prueba se
anota en la matriz de pruebas de [HOJA-DE-RUTA.md](HOJA-DE-RUTA.md).

Todo lo que sigue usa marcadores: `<ip-de-la-vm>`, `<nombre-de-la-vm>`,
`haos-prueba.tailXXXX.ts.net`, `<slug>`, `192.0.2.x`. No escribas en este
documento, en la matriz ni en ningún commit los datos reales de tu VM.

## Para qué sirve y qué no

Sirve para ejecutar contra un Supervisor de verdad lo que no se debe ejecutar
en una instalación en uso: reiniciar Core, reiniciar el host, restaurar
backups, desinstalar add-ons, borrar backups y cambiar el rol del add-on. En la
VM, si algo sale mal, se vuelve a la instantánea; en casa no hay instantánea.

No es automático. Ni el CI ni el proyecto montan esta VM, y no hay scripts
versionados para hacerlo: los comandos están aquí para que quien los ejecute
los lea uno a uno. La VM en un runner del CI con KVM es una duda abierta
(D-06 de la spec 008).

La suite normal prueba estas mismas tools con simuladores del Supervisor que
escribe el propio proyecto. Esa prueba corre siempre, pero solo demuestra que
Hermes hace lo que el simulador espera; la VM demuestra que el Supervisor real
hace lo que Hermes espera.

## Versiones

La 1.2.0 se verificó contra el Supervisor 2026.11.0 y Home Assistant Core
2026.11.1. En la VM no se pueden fijar las dos: Core sí, el Supervisor no.
Lo que sigue sale del código del Supervisor 2026.11.0.

- **Supervisor: no se puede fijar.** `POST /supervisor/update` (`ha supervisor
  update`) solo respeta `version` en el modo de desarrollo del Supervisor
  (variable de entorno `SUPERVISOR_DEV=1`, que una VM con HAOS no tiene); fuera
  de él actualiza siempre a la última publicada (`supervisor/api/supervisor.py`,
  `update`). `ha supervisor update --version 2026.11.0` no baja ni fija nada.
  Se prueba con el Supervisor que traiga la VM al día y se anota su versión
  real en la nota de cada fila de la matriz.
- **Core: sí se puede fijar.** `POST /core/update` (`ha core update --version`)
  acepta una versión concreta, anterior o posterior.
- **No desactives la actualización automática del Supervisor.** Con
  `auto_update: false`, en cuanto sale un Supervisor más nuevo, el Supervisor
  se queda «pendiente de actualizar» y la condición `supervisor_updated`
  bloquea con «supervisor needs to be updated first»: instalar y actualizar
  add-ons (`app_manager_install`, `app_manager_update`), recargar la tienda
  (`ha store reload`) y actualizar Core (`ha core update`). Es decir: no se
  podría instalar `local_hermes`, ni hacer la tanda 2, ni bajar Core para la
  prueba de la HA antigua. Además el sistema pasa a «no soportado»
  (`supervisor_version`).

Nada más terminar el onboarding, desde el add-on de terminal y SSH:

```sh
ha supervisor update      # si hay una versión nueva; si no, dice que no hay
ha core update --version 2026.11.1
ha supervisor info        # anota «version»; auto_update: true
ha core info              # version: 2026.11.1
```

Si a mitad de una tanda sale un Supervisor nuevo, lo normal es dejar que se
actualice, anotar la versión nueva en las filas que se prueben después y
repetir `ping` y `sv_get_supervisor_info` antes de seguir.

Solo si hace falta terminar una tanda con un Supervisor desactualizado (por
ejemplo, para comparar con un resultado anterior), y **solo en la VM**, se
puede pedir al Supervisor que ignore esa condición. Esto desactiva una
protección: el Supervisor lo registra como crítico («will make the system
unstable») y marca el sistema como no soportado (`job_conditions`). Desde el
add-on de terminal y SSH, que tiene acceso a la API del Supervisor:

```sh
curl -sS -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ignore_conditions": ["supervisor_updated"]}' \
  http://supervisor/jobs/options
```

Para deshacerlo, al terminar la tanda, con la misma cabecera:
`-d '{"ignore_conditions": []}' http://supervisor/jobs/options`, o
`POST http://supervisor/jobs/reset` (vuelve a las opciones por defecto). Se
comprueba con `GET http://supervisor/jobs/info`: `ignore_conditions` vacío.
Nunca en la instalación real.

La prueba de la HA antigua tiene una trampa más: con un Core de más de dos
años antes que el último publicado, el Supervisor lo marca como no soportado
y la condición `home_assistant_core_supported` bloquea `ha store reload`. Esa
prueba se hace con `local_hermes` ya en la tienda y la tienda ya recargada:
instalar no exige esa condición.

## Crear la VM

Recursos mínimos: 2 vCPU, 4 GB de RAM, 32 GB de disco, arranque UEFI. Red
aislada o NAT: la VM no necesita ver tu red de casa, solo internet para
descargar imágenes y add-ons.

Hyper-V (imagen `vhdx` de HAOS, descomprimida), en PowerShell como
administrador:

```powershell
New-VM -Name <nombre-de-la-vm> -Generation 2 -MemoryStartupBytes 4GB `
  -VHDPath .\haos_ova-<versión>.vhdx -SwitchName "Default Switch"
Set-VMProcessor -VMName <nombre-de-la-vm> -Count 2
Set-VMFirmware -VMName <nombre-de-la-vm> -EnableSecureBoot Off
Resize-VHD -Path .\haos_ova-<versión>.vhdx -SizeBytes 32GB
Start-VM -Name <nombre-de-la-vm>
```

`-EnableSecureBoot Off` hace falta porque el cargador de arranque de la imagen
de HAOS no está firmado con las claves en las que confía el firmware de una VM
de generación 2 (la plantilla por defecto solo admite el arranque de Windows):
con el arranque seguro activado, la VM no arranca. Solo afecta al firmware de
esa VM; el arranque seguro del equipo anfitrión y de las demás VMs no cambia.

QEMU/KVM con libvirt (imagen `qcow2` de HAOS, descomprimida):

```sh
qemu-img resize haos_ova-<versión>.qcow2 32G
virt-install --name <nombre-de-la-vm> --import --boot uefi \
  --vcpus 2 --memory 4096 --osinfo linux2022 \
  --disk haos_ova-<versión>.qcow2,bus=virtio \
  --network network=default --graphics none --noautoconsole
```

VMware (`vmdk`) y VirtualBox (`vdi`): sigue la guía oficial de instalación de
Home Assistant OS en una máquina virtual, con los mismos recursos.

Haz el onboarding en `http://<ip-de-la-vm>:8123` con un usuario de prueba.
Nada de la instalación real entra en la VM: ni backups, ni configuración, ni
tokens, ni la cuenta de Home Assistant Cloud.

## Instantáneas

Toma una instantánea con la VM recién preparada (Core fijado, versión del
Supervisor anotada, Hermes instalado), otra antes de cada tanda y otra antes
de cada prueba de la tanda 3.
Si una prueba deja la VM inservible, se restaura y la fila de la matriz se
anota como «falla» con la causa; nunca se repite en la instalación real.

Hyper-V:

```powershell
Checkpoint-VM -Name <nombre-de-la-vm> -SnapshotName antes-tanda-1
Restore-VMCheckpoint -VMName <nombre-de-la-vm> -Name antes-tanda-1 -Confirm:$false
```

libvirt: no uses `virsh snapshot-create-as` sin opciones. Crea una
instantánea interna, y libvirt no las admite en VMs con firmware UEFI
(`pflash`), que es como se crea esta VM (`--boot uefi`), ni encendidas ni
apagadas. Lo más sencillo y fiable es apagar la VM y copiar su disco y sus
variables UEFI (el fichero `nvram` que da `virsh dumpxml`, normalmente
`/var/lib/libvirt/qemu/nvram/<nombre-de-la-vm>_VARS.fd`):

```sh
virsh shutdown <nombre-de-la-vm>          # espera a que `virsh domstate` diga «shut off»
cp --sparse=always haos_ova-<versión>.qcow2 antes-tanda-1.qcow2
cp /var/lib/libvirt/qemu/nvram/<nombre-de-la-vm>_VARS.fd antes-tanda-1_VARS.fd
virsh start <nombre-de-la-vm>
```

Para volver a ella, con la VM apagada, se copian los dos ficheros en sentido
contrario y se arranca:

```sh
virsh destroy <nombre-de-la-vm>           # si no responde a `virsh shutdown`
cp --sparse=always antes-tanda-1.qcow2 haos_ova-<versión>.qcow2
cp antes-tanda-1_VARS.fd /var/lib/libvirt/qemu/nvram/<nombre-de-la-vm>_VARS.fd
virsh start <nombre-de-la-vm>
```

## Instalar Hermes como add-on local

1. Instala el add-on de terminal y SSH de la tienda oficial.
2. Copia la carpeta `hermes/` del repositorio (la rama que vayas a probar) a
   la carpeta de apps locales, que en ese add-on es `/addons` (o
   `/local_apps`, según la versión): `/addons/hermes/`.
3. En la copia, quita la línea `image:` de `config.yaml`. Sin ella el
   Supervisor construye la imagen desde el `Dockerfile` en vez de descargar la
   publicada.
4. Recarga la tienda (`ha store reload`) e instala el add-on local: su slug es
   `local_hermes`. La construcción tarda varios minutos.

Si el CLI de tu VM ya llama «apps» a los add-ons, los comandos `ha addons …`
de este documento son `ha apps …`.

Opciones de prueba:

- `auth_password`: genera una para la ocasión y guárdala fuera del
  repositorio. Nunca la real, nunca en un fichero versionado:

  ```sh
  python -c "import secrets; print(secrets.token_urlsafe(24))"
  ```

- `public_hostname`: el nombre con el que la VM sale por TLS (siguiente
  sección), por ejemplo `haos-prueba.tailXXXX.ts.net:8443`.
- `network_mode`: `tailscale` con Tailscale (Serve o Funnel);
  `reverse_proxy` con un proxy propio.
- El resto, por defecto. `safety_backup_enabled: true` si vas a probar los
  safety backups automáticos.

Arranca el add-on y comprueba en su log que aparece `hermes_started`.

## Conectar un cliente MCP

El emisor OAuth de Hermes es `https://<public_hostname>`: el cliente necesita
TLS delante, como en producción. Hermes en la VM pide `hassio_role: admin`:
quien llegue a él con la contraseña de prueba puede reiniciar el host,
restaurar backups y escribir en `/config`. Por eso, **por defecto la VM no se
publica en internet** y **no entra en el tailnet de tu instalación real**.

**Por defecto: Tailscale Serve, en un tailnet de pruebas.**

1. Usa un tailnet aparte para la VM: una cuenta de Tailscale de pruebas (o
   un tailnet que no tenga tu instalación real). Si de verdad tiene que ir en
   tu tailnet, dale una etiqueta propia y una política que solo le deje
   hablar con la máquina desde la que pruebas, y nunca con la instalación
   real.
2. Instala en la VM el add-on de Tailscale con un nombre de máquina propio
   (no el de tu instalación real), autorízalo en ese tailnet y deja
   desactivadas sus opciones de Funnel (`share_homeassistant`).
3. Publica Hermes **solo dentro del tailnet** con Serve:

   ```sh
   docker exec -it addon_a0d7b954_tailscale tailscale serve --bg --https=8443 8765
   docker exec -it addon_a0d7b954_tailscale tailscale serve status
   ```

   (`docker exec` desde el host de la VM; el nombre del contenedor es el del
   add-on de Tailscale de la tienda oficial.) El cliente MCP tiene que correr
   en una máquina de ese mismo tailnet, por ejemplo Claude Code en la tuya.
4. Opciones de Hermes: `network_mode: tailscale` y
   `public_hostname: haos-prueba.tailXXXX.ts.net:8443`.

Sin Tailscale, la alternativa es un **proxy inverso en la red local** con un
certificado de confianza para el cliente, con `network_mode: reverse_proxy` y
`mcp_bind` como dice `hermes/DOCS.md`, sin abrir puertos en el router.

**Funnel, solo si el cliente corre en la nube** (y no llega a tu tailnet).

> **Aviso.** `tailscale funnel` publica en internet un Hermes con rol
> `admin`, protegido solo por la contraseña de prueba. Úsalo únicamente
> mientras dure la prueba, con una contraseña generada para la ocasión, con
> la VM en el tailnet de pruebas y sin nada de la instalación real dentro.

```sh
docker exec -it addon_a0d7b954_tailscale tailscale funnel --bg --https=8443 8765
```

Al terminar (o si interrumpes la prueba), ciérralo y comprueba que ya no
hay nada publicado:

```sh
docker exec -it addon_a0d7b954_tailscale tailscale funnel --https=8443 off
docker exec -it addon_a0d7b954_tailscale tailscale funnel status
```

Conecta Claude Code (u otro cliente MCP) a
`https://haos-prueba.tailXXXX.ts.net:8443/mcp` y autoriza con la contraseña de
prueba. Antes de empezar, comprueba que `ping` responde y que
`sv_get_supervisor_info` devuelve la versión del Supervisor que anotaste.

## Tandas de pruebas

Pauta para cada tool, sin excepción:

1. **Vista previa**: la primera llamada no cambia nada (compruébalo fuera de
   Hermes) y describe exactamente el efecto que tendrá.
2. **Ejecución** con el `confirmation_token`, repitiendo los mismos
   argumentos.
3. **Efecto** comprobado fuera de Hermes: la interfaz de Home Assistant o el
   comando `ha` en la terminal.
4. **Log** de Hermes sin secretos (ni la contraseña, ni tokens, ni el
   contenido de `secrets.yaml`).

Las tools que no piden confirmación se comprueban con los pasos 3 y 4.

### Tanda 1: sin interrupción

Instantánea `antes-tanda-1`. Nada de esto reinicia ni para nada importante.

- `sv_check_core_config`: con la configuración válida y con un error
  introducido a propósito en un YAML; el resultado coincide con
  `ha core check`.
- `sv_create_backup_full` y `sv_create_backup_partial`: el backup aparece en
  `ha backups list` con el contenido pedido.
- `sv_create_safety_backup`: crea el backup con el prefijo de los safety
  backups; con `safety_backup_enabled`, la retención conserva los que diga
  `safety_backup_keep`.
- `sv_get_job_status`: con el job de un backup en curso y con uno terminado.
- `sv_set_addon_options`, sobre un add-on de prueba de la tienda oficial: el
  cambio se ve en `ha addons info <slug>` y el resto de opciones no se pierde.
- `fs_write_file`: crear y sobrescribir un fichero de prueba en `/config`; la
  vista previa enseña el diff y queda una copia de seguridad del anterior.
- `fs_move_file` y `fs_delete_file`, sobre ficheros de prueba; nunca sobre
  `configuration.yaml` ni `secrets.yaml`.
- `fs_restore_file_backup`: devolver el fichero de prueba a una copia anterior.
- `fs_set_secret`: añadir y cambiar una clave de prueba en `secrets.yaml`; ni
  la vista previa ni el log enseñan el valor.
- `sv_dismiss_resolution_issue` y `sv_dismiss_resolution_suggestion`, con un
  aviso provocado (por ejemplo, un add-on con una actualización pendiente o
  sin backup reciente): el aviso desaparece de `ha resolution info`.

### Tanda 2: add-ons

Instantánea `antes-tanda-2`. Siempre sobre un add-on de prueba de la tienda
oficial, nunca sobre los que uses de verdad.

- `sv_install_addon`: se instala y aparece en `ha addons`.
- `sv_start_addon`, `sv_stop_addon` y `sv_restart_addon`: el estado cambia
  en `ha addons info <slug>`.
- `sv_update_addon`: con una versión anterior instalada; termina en la versión
  nueva.
- `sv_uninstall_addon`: desaparece; la vista previa avisa de que sus datos se
  pierden.
- Sobre `local_hermes`, solo la vista previa, sin confirmar: la de
  `sv_stop_addon` lleva el aviso de autoprotección, y `sv_update_addon` se
  rechaza antes de llamar al Supervisor (spec 009, CAP-021).

### Tanda 3: interrupciones, una por instantánea

Instantánea antes de cada una; después de cada una, comprobar que Hermes
vuelve (`ping`) y restaurar si algo queda mal.

- `sv_restart_core`: la vista previa dice si la configuración es válida; Core
  vuelve y Hermes se reconecta.
- `sv_reboot_host`: la VM reinicia y Hermes arranca solo.
- `sv_delete_backup`: sobre un backup creado en la tanda 1.
- `sv_restore_backup_partial`: restaurar solo una carpeta o un add-on de
  prueba y comprobar que lo demás no cambia.
- `sv_restore_backup_full`: restaurar el backup completo de la tanda 1; Core
  vuelve con el estado de entonces.

### Tools nuevas del programa

Las `sv_*` que añadan las sub-features siguientes de la 1.2.0 siguen la misma
pauta, en la tanda que les toque por su efecto. Cada sub-feature que añada una
tool del Supervisor o de ficheros añade aquí su línea y su fila en la matriz.

- `sv_call_api` (la genérica del Supervisor de la 011), en la tanda 3: con una
  ruta que la tabla de clasificación marque `confirm`, por ejemplo
  `POST /dns/restart`, la vista previa enseña el método, la ruta, la
  plantilla y la categoría, y la ejecución reinicia el plugin DNS
  (`ha dns info`); una ruta `deny`, una de Hermes (`local_hermes`) o el
  proxy de Core se rechazan sin llegar al Supervisor.
- `ha_update_http_config` y `ha_promote_http_config` (red y HTTP de Core,
  spec 021), en la tanda 3: confirmar reinicia Core. Cambiar
  `cors_allowed_origins` (o el puerto, si la interfaz se vuelve a abrir en el
  nuevo): Core reinicia con la configuración pendiente (`ha_read_ws_command`
  de `http/config`: `active_config_type` `pending` y `revert_at`), Hermes se
  reconecta por el Supervisor, y sin promover Core vuelve a la estable y
  reinicia a los 5 minutos. Repetir y promover con `ha_promote_http_config`
  antes de que pase el plazo: la configuración nueva queda como estable y no
  se revierte. Un `server_host` sin `0.0.0.0` ni `172.30.32.1` se rechaza sin
  tocar nada.

## Probar hassio_role: manager

El add-on publicado pide `hassio_role: admin`. Según el código del Supervisor
2026.11.0, todas las rutas que usa Hermes caben en `manager`
(`tests/test_rutas_supervisor_rol.py`, sin excepciones); esta prueba lo
comprueba con un Supervisor real.

1. Instantánea `antes-rol`.
2. En la copia local, cambia `hassio_role: admin` por `hassio_role: manager`
   en `config.yaml`, recarga la tienda y reconstruye `local_hermes`
   (`ha addons rebuild local_hermes`, o desinstalar e instalar).
3. Comprueba:
   - el arranque completo (`hermes_started` en el log);
   - `sv_get_addon_options` y las opciones que devuelve `sv_get_addon` sobre
     otro add-on (con un rol menor, el Supervisor las devuelve vacías);
   - todas las `sv_*` de la matriz, de lectura y de escritura, con la pauta de
     las tandas.
4. Criterio de éxito: ningún 403 nuevo en el log del Supervisor
   (`ha supervisor logs`) ni en las respuestas de Hermes.

El rol del add-on publicado no cambia por esta prueba: bajarlo es la decisión
D-02 de la spec 008, que se toma con este resultado delante.

## Pruebas manuales que se pueden hacer en la VM

Casillas de «Pruebas manuales pendientes» de la hoja de ruta que no necesitan
la instalación real:

- **Confirmar `fs_write_file` sin el documento** con un fichero de prueba
  grande, y comprobar que, pasados unos dos minutos,
  `/data/pending_confirmations` del add-on no conserva el contenido. El `/data`
  del add-on se ve desde el host de la VM, no desde las tools.
- **Clave `homeassistant` en una HA antigua**: con Core anterior a 2024.10
  (`ha core update --version <versión-antigua>`), el Supervisor rechaza
  instalar o actualizar Hermes con un error claro. Recarga la tienda antes de
  bajar Core: con un Core de más de dos años, `ha store reload` queda
  bloqueado (sección «Versiones»).
- **`sv_get_resolution` con avisos reales**: las referencias salen redactadas.
- **Trazas de un script**: `ha_list_traces` y `ha_get_trace` con
  `domain: "script"`.
- **Diagnóstico del Supervisor (spec 013)**: las once tools de
  `system_diagnostics` (logs de Core, del Supervisor, de los plugins y del
  host, también con `boot=-1` y `latest`; `sv_get_disk_usage` con
  `max_depth` 3 y con un montaje; las tres de OS) y las rutas `read` de la
  tabla por `sv_read_api`. Solo leen: no entran en «Tandas de pruebas», que
  es de las tools que modifican.

## Anotar el resultado

En la matriz de la hoja de ruta, cambia `pendiente` por:

- `ok`, con la versión de Hermes y la fecha en la nota (por ejemplo,
  `1.2.0, 2026-12-01`);
- `falla`, con la causa o el hallazgo en la nota, y abre la incidencia.

Marca la casilla manual que corresponda. En las notas, nada de la VM: ni IPs,
ni nombres de máquina, ni slugs de add-ons que no sean los de la tienda
oficial. `tests/test_matriz_pruebas.py` rechaza un `ok` sin versión y fecha y
un `falla` sin nota.

## Limpiar

- Borra la VM, o vuelve a la instantánea inicial si la vas a reutilizar.
- Si usaste Funnel, ciérralo (`tailscale funnel --https=8443 off`) antes de
  nada y comprueba con `tailscale funnel status` que no queda nada publicado.
- Quita el nodo de la VM del tailnet de pruebas en la consola de Tailscale
  (o borra el tailnet de pruebas si solo servía para esto).
- No conserves los backups de la VM ni la contraseña de prueba.
