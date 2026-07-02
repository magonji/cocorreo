"""Configuration store for the cocorreo archive.

Manages the data directory: persistent configuration (scrypt salt,
KDF parameters, verification token) and the passphrase unlock flow.

Data directory layout:
    data/
    ├── .cocorreo-config.json   # KDF parameters + encrypted verification token
    ├── cocorreo.db             # SQLite/SQLCipher
    └── attachments/            # AES-GCM blobs, sharded by first hex byte
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


class NotInitialised(KeystoreError):
    pass


class AlreadyInitialised(KeystoreError):
    pass


@dataclass
class Keystore:
    """In-memory state after unlocking a data directory."""

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


def is_initialised(data_dir: Path) -> bool:
    return _config_path(data_dir).is_file()


def initialise(data_dir: Path, passphrase: str) -> Keystore:
    """Creates the initial configuration: scrypt salt, verification token.

    Fails if `.cocorreo-config.json` already exists in `data_dir`.
    """
    data_dir = data_dir.expanduser().resolve()
    if is_initialised(data_dir):
        raise AlreadyInitialised(f"{data_dir} is already initialised")

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "attachments").mkdir(exist_ok=True)

    salt = os.urandom(SALT_LEN)
    master = crypto.derive_master(passphrase, salt)
    keys = crypto.derive_keys(master)

    # Verification token: encrypt a known plaintext with attach_key.
    # On unlock, we try to decrypt it; if it fails, the passphrase is wrong.
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
    """Loads the configuration, derives the keys, verifies the passphrase."""
    data_dir = data_dir.expanduser().resolve()
    cfg_path = _config_path(data_dir)
    if not cfg_path.is_file():
        raise NotInitialised(f"{data_dir} is not initialised (missing {CONFIG_FILENAME})")

    config = json.loads(cfg_path.read_text())
    if config.get("version") != CONFIG_VERSION:
        raise KeystoreError(f"unsupported config version: {config.get('version')!r}")

    kdf = config["kdf"]
    if kdf.get("algorithm") != "scrypt":
        raise KeystoreError(f"unsupported KDF algorithm: {kdf.get('algorithm')!r}")
    salt = base64.b64decode(kdf["salt_b64"])

    # Reproduce exactly the stored parameters.
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    master = Scrypt(salt=salt, length=crypto.KEY_LEN, n=kdf["n"], r=kdf["r"], p=kdf["p"]).derive(
        passphrase.encode("utf-8")
    )
    keys = crypto.derive_keys(master)

    verify_blob = base64.b64decode(config["verify_b64"])
    try:
        plaintext = crypto.decrypt_bytes(verify_blob, keys.attach_key)
    except Exception as e:
        raise WrongPassphrase("incorrect passphrase") from e
    if plaintext != VERIFY_PLAINTEXT:
        raise WrongPassphrase("invalid verification token")

    return Keystore(data_dir=data_dir, keys=keys)


def prompt_passphrase(confirm: bool = False) -> str:
    """Asks for the passphrase via stdin/tty without echo. Raises if stdin isn't interactive."""
    import getpass

    if not sys.stdin.isatty():
        raise KeystoreError("an interactive terminal is required to read the passphrase")
    pw = getpass.getpass("Passphrase: ")
    if not pw:
        raise KeystoreError("empty passphrase")
    if confirm:
        pw2 = getpass.getpass("Confirm passphrase: ")
        if pw != pw2:
            raise KeystoreError("passphrases don't match")
    return pw
