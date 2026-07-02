"""Parser streaming de archivos mbox.

Itera por mensajes sin cargar el archivo entero en memoria. Adecuado para
archivos de 20+ GB que no caben en RAM.

Algoritmo (mbox-O, el que usa Thunderbird):
    Cada mensaje empieza con una línea 'From ' a columna 0, seguida del
    bloque RFC 5322 (headers + cuerpo). El siguiente 'From ' a columna 0
    marca el fin del mensaje anterior. En el cuerpo, líneas que comienzan
    por 'From ' se escapan a '>From ' al escribir el mbox.

Limitaciones:
    No deshacemos el escape '>From ' → 'From ' al devolver bytes. El
    parser MIME no se ve afectado porque la línea sigue siendo cuerpo.
    Si el mbox es de variante RD (sin escape), un cuerpo con 'From '
    a inicio de línea provocará un split incorrecto. Lo aceptamos: el
    importer registrará el mensaje afectado en `import_runs.notes`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

FROM_PREFIX = b"From "


def iter_messages(path: Path) -> Iterator[tuple[int, bytes]]:
    """Genera `(offset_de_la_línea_From, bytes_del_mensaje_sin_From_)` por mensaje.

    Los bytes devueltos NO incluyen la línea 'From ' separadora — son los
    bytes RFC 5322 puros listos para pasar al parser de email.
    """
    with path.open("rb") as f:
        # Localizar la primera línea 'From '. Algunos archivos pueden tener
        # basura inicial; saltamos hasta encontrar el primer separador.
        msg_offset = -1
        offset = 0
        first_line = f.readline()
        if not first_line:
            return  # archivo vacío
        if first_line.startswith(FROM_PREFIX):
            msg_offset = 0
            offset = len(first_line)
        else:
            # Buscar el primer 'From '
            offset = len(first_line)
            while True:
                line = f.readline()
                if not line:
                    return
                if line.startswith(FROM_PREFIX):
                    msg_offset = offset
                    offset += len(line)
                    break
                offset += len(line)

        # A partir de aquí, acumulamos cuerpo del mensaje en buffer.
        # Cuando vemos otro 'From ' a columna 0, yieldeamos.
        buffer = bytearray()
        while True:
            line = f.readline()
            if not line:
                if buffer:
                    yield msg_offset, bytes(buffer)
                return
            if line.startswith(FROM_PREFIX):
                yield msg_offset, bytes(buffer)
                buffer.clear()
                msg_offset = offset
                offset += len(line)
            else:
                buffer.extend(line)
                offset += len(line)
