"""Constantes de `banco_flujos`.

Configuración del banco de pruebas de Core (spec 016): corre dentro de la HA
de prueba del CI. Nunca se empaqueta ni llega al add-on.
"""

DOMAIN = "banco_flujos"

# El descubrimiento que se abre al arrancar (`banco_flujos:` en
# configuration.yaml). Los tests que lo ignoran abren antes uno propio con el
# servicio `banco_flujos.descubrir` y un unique_id aleatorio: un descubrimiento
# ignorado no vuelve, y cada test tiene que poder correr solo.
UNIQUE_ID_INICIAL = "banco-flujos-inicial"
NOMBRE_INICIAL = "Banco descubierto"

# Los dos avisos reparables (los usa el tramo C de la 016): uno para
# arreglarlo y otro para abrir su flujo y abortarlo.
AVISO_REPARABLE = "aviso_reparable"
AVISO_PARA_ABORTAR = "aviso_para_abortar"

# Tipo de subentry (tramo B): un sensor por subentry.
SUBENTRY_ELEMENTO = "elemento"
