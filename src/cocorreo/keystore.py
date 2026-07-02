"""Almacén de configuración del archivo cocorreo.

Gestiona el directorio de datos: configuración persistente (salt scrypt,
parámetros KDF, token de verificación) y flujo de unlock con passphrase.

Layout del directorio de datos:
    data/
    ├── .cocorreo-config.json   # parámetros KDF + token de verificación cifrado
    ├── cocorreo.db             # SQLite/SQLCipher
    └── attachments/            # blobs AES-GCM, sharded por primer byte hex
"""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import crypto

CONFIG_FILENAME = ".cocorreo-config.json"
CONFIG_VERSION = 1
VERIFY_PLAINTEXT = b"cocorreo-verify-v1"
SALT_LEN = 16


class KeystoreError(Exception):
    pass


class WrongPassphrase(KeystoreError):
    pass


class NotInitialized(KeystoreError):
    pass


class AlreadyInitialized(KeystoreError):
    pass


@dataclass
class Keystore:
    """Estado en memoria tras desbloquear un directorio de datos."""

    data_dir: Path
    keys: crypto.DerivedKeys

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cocorreo.db"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"


def _config_path(data_dir: Path) -> Path:
    return data_dir / CONFIG_FILENAME


def is_initialized(data_dir: Path) -> bool:
    return _config_path(data_dir).is_file()


def initialize(data_dir: Path, passphrase: str) -> Keystore:
    """Crea la configuración inicial: salt scrypt, token de verificación.

    Falla si ya existe `.cocorreo-config.json` en `data_dir`.
    """
    data_dir = data_dir.expanduser().resolve()
    if is_initialized(data_dir):
        raise AlreadyInitialized(f"{data_dir} ya está inicializado")

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "attachments").mkdir(exist_ok=True)

    salt = os.urandom(SALT_LEN)
    master = crypto.derive_master(passphrase, salt)
    keys = crypto.derive_keys(master)

    # Token de verificación: cifrar un plaintext conocido con attach_key.
    # En unlock, intentamos descifrarlo; si falla, la passphrase es incorrecta.
    verify_blob = crypto.encrypt_bytes(VERIFY_PLAINTEXT, keys.attach_key)

    config = {
        "version": CONFIG_VERSION,
        "kdf": {
            "algorithm": "scrypt",
            "n": crypto.SCRYPT_N,
            "r": crypto.SCRYPT_R,
            "p": crypto.SCRYPT_P,
            "salt_b64": base64.b64encode(salt).decode("ascii"),
        },
        "verify_b64": base64.b64encode(verify_blob).decode("ascii"),
    }
    cfg_path = _config_path(data_dir)
    cfg_path.write_text(json.dumps(config, indent=2))
    os.chmod(cfg_path, 0o600)

    return Keystore(data_dir=data_dir, keys=keys)


def unlock(data_dir: Path, passphrase: str) -> Keystore:
    """Carga la configuración, deriva las claves, verifica la passphrase."""
    data_dir = data_dir.expanduser().resolve()
    cfg_path = _config_path(data_dir)
    if not cfg_path.is_file():
        raise NotInitialized(f"{data_dir} no está inicializado (falta {CONFIG_FILENAME})")

    config = json.loads(cfg_path.read_text())
    if config.get("version") != CONFIG_VERSION:
        raise KeystoreError(f"versión de config no soportada: {config.get('version')!r}")

    kdf = config["kdf"]
    if kdf.get("algorithm") != "scrypt":
        raise KeystoreError(f"algoritmo KDF no soportado: {kdf.get('algorithm')!r}")
    salt = base64.b64decode(kdf["salt_b64"])

    # Reproducimos exactamente los parámetros guardados.
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    master = Scrypt(salt=salt, length=crypto.KEY_LEN, n=kdf["n"], r=kdf["r"], p=kdf["p"]).derive(
        passphrase.encode("utf-8")
    )
    keys = crypto.derive_keys(master)

    verify_blob = base64.b64decode(config["verify_b64"])
    try:
        plaintext = crypto.decrypt_bytes(verify_blob, keys.attach_key)
    except Exception as e:
        raise WrongPassphrase("passphrase incorrecta") from e
    if plaintext != VERIFY_PLAINTEXT:
        raise WrongPassphrase("token de verificación inválido")

    return Keystore(data_dir=data_dir, keys=keys)


def prompt_passphrase(confirm: bool = False) -> str:
    """Pide la passphrase por stdin/tty sin echo. Lanza si stdin no es interactivo."""
    import getpass

    if not sys.stdin.isatty():
        raise KeystoreError("se requiere terminal interactivo para leer la passphrase")
    pw = getpass.getpass("Passphrase: ")
    if not pw:
        raise KeystoreError("passphrase vacía")
    if confirm:
        pw2 = getpass.getpass("Confirma passphrase: ")
        if pw != pw2:
            raise KeystoreError("las passphrases no coinciden")
    return pw
