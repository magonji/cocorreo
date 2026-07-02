"""Primitivas criptográficas.

Derivación de claves desde la passphrase del usuario (scrypt → HKDF) y
cifrado AEAD streaming (AES-256-GCM) para adjuntos.

Política de claves:
    passphrase  ──[scrypt]──>  master(32B)
    master      ──[HKDF "cocorreo-db"]──>          db_key(32B)
    master      ──[HKDF "cocorreo-attachments"]──> attach_key(32B)

`db_key` se pasa a SQLCipher como clave raw hex (sin KDF adicional).
`attach_key` cifra cada adjunto con AES-256-GCM y nonce único por archivo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# Tamaños de scrypt. N=2^15 da ~128 MB de RAM, ~200 ms en hardware moderno,
# ~1 s en una Raspberry Pi 4/5. Cómodo para uso interactivo, no para fuerza bruta.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32

NONCE_LEN = 12  # AES-GCM estándar
TAG_LEN = 16
CHUNK_SIZE = 1024 * 1024  # 1 MB


@dataclass(frozen=True)
class DerivedKeys:
    """Conjunto de claves derivadas tras desbloquear el almacén."""

    db_key: bytes
    attach_key: bytes

    @property
    def db_key_hex(self) -> str:
        return self.db_key.hex()


def derive_master(passphrase: str, salt: bytes) -> bytes:
    """Aplica scrypt a la passphrase para obtener una clave maestra de 32 bytes."""
    if not passphrase:
        raise ValueError("passphrase vacía")
    if len(salt) < 16:
        raise ValueError("salt demasiado corto (mínimo 16 bytes)")
    kdf = Scrypt(salt=salt, length=KEY_LEN, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(passphrase.encode("utf-8"))


def derive_keys(master: bytes) -> DerivedKeys:
    """Deriva las dos claves de uso (BD + adjuntos) desde la clave maestra."""
    if len(master) != KEY_LEN:
        raise ValueError(f"master debe tener {KEY_LEN} bytes")
    db_key = HKDF(
        algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=b"cocorreo-db"
    ).derive(master)
    attach_key = HKDF(
        algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=b"cocorreo-attachments"
    ).derive(master)
    return DerivedKeys(db_key=db_key, attach_key=attach_key)


def encrypt_file(src: BinaryIO, dst: BinaryIO, key: bytes) -> None:
    """Cifra un stream binario a otro stream binario con AES-256-GCM.

    Formato de salida:
        nonce (12 B) || ciphertext (N B) || tag (16 B)

    Streaming: memoria acotada a `CHUNK_SIZE`. Adecuado para adjuntos de
    cualquier tamaño.
    """
    nonce = os.urandom(NONCE_LEN)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
    enc = cipher.encryptor()
    dst.write(nonce)
    while True:
        chunk = src.read(CHUNK_SIZE)
        if not chunk:
            break
        dst.write(enc.update(chunk))
    dst.write(enc.finalize())
    dst.write(enc.tag)


def decrypt_file(src_path: Path, dst: BinaryIO, key: bytes) -> None:
    """Descifra un archivo en formato `nonce||ct||tag` a un stream destino.

    Necesita un archivo seekable porque el tag está al final (GCM requiere
    el tag antes de empezar la verificación). Para adjuntos en disco esto
    no es restrictivo.
    """
    size = src_path.stat().st_size
    if size < NONCE_LEN + TAG_LEN:
        raise ValueError(f"archivo demasiado pequeño para ser un blob cifrado: {src_path}")
    with src_path.open("rb") as f:
        nonce = f.read(NONCE_LEN)
        f.seek(size - TAG_LEN)
        tag = f.read(TAG_LEN)
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag))
        dec = cipher.decryptor()
        ct_remaining = size - NONCE_LEN - TAG_LEN
        f.seek(NONCE_LEN)
        while ct_remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, ct_remaining))
            if not chunk:
                break
            ct_remaining -= len(chunk)
            dst.write(dec.update(chunk))
        dst.write(dec.finalize())


def iter_decrypt(src_path: Path, key: bytes, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
    """Generador que descifra un blob al vuelo en chunks. Ideal para streaming HTTP.

    Mismo formato de entrada que `decrypt_file` (`nonce(12)||ct||tag(16)`); el tag
    se lee primero (seek al final), luego se descifra el cuerpo en chunks y al
    final se cierra con `finalize()` (que verifica el tag GCM).
    """
    size = src_path.stat().st_size
    if size < NONCE_LEN + TAG_LEN:
        raise ValueError(f"archivo demasiado pequeño para ser blob cifrado: {src_path}")
    with src_path.open("rb") as f:
        nonce = f.read(NONCE_LEN)
        f.seek(size - TAG_LEN)
        tag = f.read(TAG_LEN)
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag))
        dec = cipher.decryptor()
        ct_remaining = size - NONCE_LEN - TAG_LEN
        f.seek(NONCE_LEN)
        while ct_remaining > 0:
            chunk = f.read(min(chunk_size, ct_remaining))
            if not chunk:
                break
            ct_remaining -= len(chunk)
            piece = dec.update(chunk)
            if piece:
                yield piece
        final = dec.finalize()
        if final:
            yield final


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    """Cifra un blob pequeño en memoria. Útil para tokens de verificación."""
    nonce = os.urandom(NONCE_LEN)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
    enc = cipher.encryptor()
    ct = enc.update(data) + enc.finalize()
    return nonce + ct + enc.tag


def decrypt_bytes(blob: bytes, key: bytes) -> bytes:
    """Descifra un blob pequeño cifrado con `encrypt_bytes`."""
    if len(blob) < NONCE_LEN + TAG_LEN:
        raise ValueError("blob demasiado pequeño")
    nonce = blob[:NONCE_LEN]
    tag = blob[-TAG_LEN:]
    ct = blob[NONCE_LEN:-TAG_LEN]
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag))
    dec = cipher.decryptor()
    return dec.update(ct) + dec.finalize()
