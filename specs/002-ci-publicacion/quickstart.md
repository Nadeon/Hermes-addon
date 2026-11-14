# Guía de validación: publicación con las actions nuevas

## En local (sin Docker)

1. Sintaxis de los workflows: `actionlint .github/workflows/*.yml` → sin errores.
2. Ninguna referencia al builder retirado ni a ramas:
   `grep -rnE "builder@master|@(main|master)$" .github/workflows/` → nada.
3. La suite: `pytest -q` → todo en verde (hay tests que leen `config.yaml` y el Dockerfile).
4. Control negativo de la comprobación (principio VII): ejecutar el script del
   paso «Leer y comprobar el manifiesto» contra una copia de `config.yaml` con
   `timeout: 10`, y contra otra con `image:` sin `{arch}` → las dos deben fallar;
   con el manifiesto real debe pasar y emitir una matriz de 2 filas.

## En GitHub

1. Abrir la PR: el workflow «Publicar imagen» ejecuta `comprobar`,
   `Validar amd64` y `Validar aarch64` → verde; ninguna etiqueta nueva en los
   paquetes `hermes-amd64` / `hermes-aarch64`.
2. Tras fusionar y subir la versión, lanzar «Etiquetar versión»: la etiqueta
   dispara «Publicar imagen» → `Publicar amd64` y `Publicar aarch64` en verde, y
   existen `ghcr.io/nadeon/hermes-<arch>:<versión>`.
3. `cosign verify ghcr.io/nadeon/hermes-amd64:<versión> --certificate-identity-regexp 'https://github.com/Nadeon/Hermes-addon/.*' --certificate-oidc-issuer https://token.actions.githubusercontent.com` → firma válida.
4. En un Home Assistant de pruebas, actualizar la app → descarga la imagen y arranca.
5. Relanzar «Publicar imagen» a mano con la misma versión → aviso de que la
   etiqueta ya existe; nada se sobrescribe.
