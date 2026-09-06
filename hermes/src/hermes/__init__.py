"""Hermes — MCP Home Assistant Add-on."""

# Tiene que coincidir con `version:` de config.yaml. No se deriva de ahí
# porque config.yaml no viaja en la imagen —el Dockerfile solo copia src/ y
# run.sh—, así que la sincronía la garantiza un test del manifiesto.
__version__ = "1.0.2"
