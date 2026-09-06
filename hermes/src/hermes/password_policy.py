"""Hermes — Calidad de `auth_password`.

`auth_password` es el único secreto que separa internet de una casa entera, y
el login ya tiene un freno global anti-fuerza-bruta (ver `oauth.py`). Ese freno
deja el techo de un atacante en unos 2.000 intentos al día, y no se puede subir
rotando de IP porque el contador es global.

Con ese techo, una password de 12 caracteres al azar es inalcanzable —del orden
de 10^15 años— y hasta una mediocre de 30 bits aguanta siglos. El único caso
que la aritmética deja abierto es la password *predecible*: si está entre el
millón más usado, caen en unos ocho meses. Eso es lo que comprueba este módulo,
y por eso no comprueba nada más.

Las reglas siguen NIST SP 800-63B §5.1.1.2, que prohíbe expresamente las reglas
de composición ("una mayúscula, un número y un símbolo": empujan a la gente a
`Password1!` y no añaden entropía real) y en su lugar manda rechazar listas de
passwords conocidas, secuencias, repeticiones y palabras del propio contexto.

Ninguna función de este módulo devuelve, registra ni interpola la password en su
mensaje de error: el motivo se explica sin citarla.
"""

from __future__ import annotations

# Longitud mínima. 12 caracteres al azar son ~71 bits: con el techo de 2.000
# intentos diarios del login, inalcanzable.
MIN_AUTH_PASSWORD_LENGTH = 12

# Mínimo de caracteres DISTINTOS. Calibrado sobre 200.000 passwords generadas
# al azar: con 5 no hay ni un falso positivo en alfabetos a-zA-Z0-9 de 12 y 16
# caracteres ni en base64, y atrapa `aaaaaaaaaaaa`, `abababababab` y
# `abcabcabcabc`. Subirlo a 6 empezaría a rechazar hexadecimal legítimo.
MIN_CARACTERES_DISTINTOS = 5

# Longitud a partir de la cual un tramo consecutivo (del abecedario, de los
# dígitos o de una fila del teclado) delata que la password se tecleó "a
# rodillo" en vez de generarse.
LARGO_SECUENCIA = 6

# Secuencias que la gente usa como password. Se comprueban en los dos sentidos.
_SECUENCIAS = (
    "abcdefghijklmnopqrstuvwxyz",
    "0123456789",
    "qwertyuiop", "asdfghjkl", "zxcvbnm",      # QWERTY
    "qwertzuiop",                               # QWERTZ (DE)
    "azertyuiop", "qsdfghjklm",                 # AZERTY (FR)
)

# Palabras del propio contexto: NIST las llama "context-specific words" y las
# pone al mismo nivel que las del diccionario, porque son las primeras que
# prueba quien sabe qué está atacando.
#
# Todas tienen 6 caracteres o más a propósito. La comparación es en minúsculas,
# así que una palabra de 3 letras aparecería por puro azar dentro de 1 de cada
# 3.000 passwords aleatorias, y rechazar una password legítima cuesta más que
# dejar pasar «mcp».
_LARGO_MINIMO_PALABRA = 6
_PALABRAS_DEL_CONTEXTO = (
    "hermes", "homeassistant", "home-assistant", "home assistant",
    "hassio", "supervisor",
)

# Passwords conocidas de 12 caracteres o más. Las más cortas no hacen falta:
# no llegan aquí, las para el mínimo de longitud. Comparación en minúsculas.
_CONOCIDAS = frozenset({
    "000000000000", "111111111111", "121212121212", "123123123123",
    "123456789012", "1234567890123", "12345678901234", "123456789012345",
    "1234567890abc", "1q2w3e4r5t6y", "1qaz2wsx3edc", "zaq12wsxcde3",
    "qazwsxedcrfv", "asdfghjkl123", "qwertyuiop123", "qwertyuiopasdf",
    "abcd1234abcd", "abcd1234efgh", "password1234", "password12345",
    "password123456", "passwordpassword", "passw0rd1234", "p@ssw0rd1234",
    "administrator", "adminadminadmin", "administrador",
    "letmein123456", "welcome123456", "welcomewelcome",
    "iloveyou1234", "iloveyou12345", "trustno1trustno1",
    "football12345", "baseball12345", "superman1234", "batman123456",
    "princess1234", "sunshine1234", "babygirl12345", "michaeljordan",
    "contrasena123", "contraseña123", "contrasena1234", "contraseña1234",
    "micontrasena1", "micontraseña1", "españa123456", "espana123456",
    "homeassistant", "homeassistant1", "homeassistant123",
    "changeme12345", "cambiaresto12", "temporal12345",
})


def _sin_repetir(texto: str) -> str:
    """Caracteres distintos, en orden de primera aparición."""
    vistos: list[str] = []
    for c in texto:
        if c not in vistos:
            vistos.append(c)
    return "".join(vistos)


def _es_unidad_repetida(texto: str) -> bool:
    """True si el texto es un trozo corto repetido hasta llenar (`abcabcabc`)."""
    for largo in range(1, len(texto) // 2 + 1):
        if len(texto) % largo == 0 and texto == texto[:largo] * (len(texto) // largo):
            return True
    return False


def _tramo_consecutivo(texto: str) -> bool:
    """True si contiene un tramo largo de una secuencia, en cualquier sentido."""
    for secuencia in _SECUENCIAS:
        candidatas = (secuencia, secuencia[::-1])
        for inicio in range(len(texto) - LARGO_SECUENCIA + 1):
            tramo = texto[inicio:inicio + LARGO_SECUENCIA]
            if any(tramo in c for c in candidatas):
                return True
    return False


def _distintos_llegan_en_orden(texto: str) -> bool:
    """True si los caracteres distintos van APARECIENDO en orden de secuencia.

    Atrapa lo que el tramo consecutivo no ve porque está entrelazado:
    `112233445566` estrena los dígitos del 1 al 6, en ese orden y sin nada más.

    Lo que importa es el orden de aparición, no el conjunto. Un número de 16
    dígitos sacado de un generador usa también casi todos los dígitos, pero los
    estrena en un orden cualquiera; exigir que salgan ordenados es lo que
    distingue el patrón tecleado del azar.
    """
    orden = _sin_repetir(texto)
    if len(orden) < MIN_CARACTERES_DISTINTOS:
        return False          # ya lo rechaza la regla de variedad
    return any(orden in s or orden in s[::-1] for s in _SECUENCIAS)


def _etiquetas_del_hostname(hostname: str) -> list[str]:
    """Trozos del hostname que son lo bastante largos como para adivinarse.

    El corte de longitud es el mismo que el de las palabras del contexto y por
    la misma razón: una etiqueta de 4 letras como `tail` sale por azar dentro
    de passwords legítimas.
    """
    limpio = hostname.split(":")[0].lower()
    return [t for t in limpio.replace("-", ".").split(".")
            if len(t) >= _LARGO_MINIMO_PALABRA]


def motivo_debil(password: str, *, public_hostname: str = "") -> str | None:
    """Devuelve por qué la password es débil, o None si pasa.

    El mensaje NUNCA incluye la password: se explica la regla, no el valor.
    """
    if len(password) < MIN_AUTH_PASSWORD_LENGTH:
        return (
            f"tiene {len(password)} caracteres y el mínimo son "
            f"{MIN_AUTH_PASSWORD_LENGTH}"
        )

    bajita = password.lower()

    if len(set(password)) < MIN_CARACTERES_DISTINTOS:
        return (
            f"solo usa {len(set(password))} caracteres distintos; una password "
            f"generada al azar usa casi tantos como su longitud"
        )

    if _es_unidad_repetida(password):
        return "es un trozo corto repetido hasta llenar la longitud"

    if _tramo_consecutivo(bajita):
        return (
            "contiene una tirada seguida del abecedario, de los dígitos o de "
            "una fila del teclado"
        )

    if _distintos_llegan_en_orden(bajita):
        return "estrena sus caracteres en orden, como una tirada tecleada seguida"

    if bajita in _CONOCIDAS:
        return "está en las listas de passwords más usadas"

    for palabra in _PALABRAS_DEL_CONTEXTO:
        if palabra in bajita:
            return (
                f"contiene «{palabra}», que es lo primero que prueba quien sabe "
                f"qué está atacando"
            )

    for etiqueta in _etiquetas_del_hostname(public_hostname):
        if etiqueta in bajita:
            return (
                "contiene un trozo de tu propio hostname público, que es "
                "justo por donde llega el atacante"
            )

    return None
