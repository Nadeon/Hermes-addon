# Quickstart: comprobar la 034

## En la suite (Windows, Git Bash, desde la raíz del worktree)

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta temporal propia>)" \
  <python del .venv del checkout principal> -m pytest -q -p no:cacheprovider \
  tests/test_folders.py tests/test_tools_folders.py tests/test_tools_folders_write.py \
  tests/test_tools_privilegios.py
```

Las raíces de `/addons` y `/share` de los tests son carpetas temporales
(`folders.ADDONS_BASE`, `folders.SHARE_BASE` parcheadas con `tmp_path`); el
Supervisor es simulado. La suite completa tiene que acabar con los 6 fallos
conocidos de Windows y nada más; la referencia es el CI de Linux.

## En la VM de la 014 (después, con la app instalada como local)

Pruebas manuales que quedan pendientes en `docs/HOJA-DE-RUTA.md` (nunca con
las tools conectadas a la instalación real del mantenedor):

1. `fs_list_dir_in_folder(folder="addons")` lista las apps locales;
   `fs_stat_in_folder` de una carpeta dice su `local_<slug>` y si está
   instalada.
2. Crear una carpeta de prueba en `/share` con `fs_create_dir_in_folder`,
   escribir un fichero con `fs_write_file_in_folder`, renombrarla con
   `fs_move_in_folder` y borrarla con `fs_delete_in_folder(recursive=true)`;
   cada una en dos pasos.
3. Borrar la carpeta de una app local instalada: rechazado con
   `installed_app`. Desinstalarla y repetir: vista previa con el recuento y,
   al confirmar, borrada.
4. `sv_install_addon` de una app local con `map` y `privileged`: la vista
   previa enseña `privileges` con `declared_in_folder` y `elevated`.
5. El log del Supervisor muestra el aviso del tipo de montaje heredado
   `addons` (esperado, research R-1).
