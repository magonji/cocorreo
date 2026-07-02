"""Cryptographic primitives.

Key derivation from the user's passphrase (scrypt → HKDF) and streaming
AEAD encryption (AES-256-GCM) for attachments.

Key policy:
    passphrase  ──[scrypt]──>  master(32B)
    master      ──[HKDF "cocorreo-db"]──>          db_key(32B)
    master      ──[HKDF "cocorreo-attachments"]──> attach_key(32B)

`db_key` is passed to SQLCipher as a raw hex key (no additional KDF).
`attach_key` encrypts each attachment with AES-256-GCM and a unique nonce per file.
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

# scrypt sizing. N=2^15 gives ~128 MB of RAM, ~200 ms on modern hardware,
# ~1 s on a Raspberry Pi 4/5. Comfortable for interactive use, not for brute force.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32

NONCE_LEN = 12  # standard AES-GCM
TAG_LEN = 16
CHUNK_SIZE = 1024 * 1024  # 1 MB


@dataclass(frozen=True)
class DerivedKeys:
    """Set of keys derived once the store has been unlocked."""

    db_key: bytes
    attach_key: bytes

    @property
    def db_key_hex(self) -> str:
        return self.db_key.hex()


def derive_master(passphrase: str, salt: bytes) -> bytes:
    """Applies scrypt to the passphrase to obtain a 32-byte master key."""
    if not passphrase:
        raise ValueError("empty passphrase")
    if len(salt) < 16:
        raise ValueError("salt too short (minimum 16 bytes)")
    kdf = Scrypt(salt=salt, length=KEY_LEN, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(passphrase.encode("utf-8"))


def derive_keys(master: bytes) -> DerivedKeys:
    """Derives the two usage keys (DB + attachments) from the master key."""
    if len(master) != KEY_LEN:
        raise ValueError(f"master must be {KEY_LEN} bytes long")
    db_key = HKDF(
        algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=b"cocorreo-db"
    ).derive(master)
    attach_key = HKDF(
        algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=b"cocorreo-attachments"
    ).derive(master)
    return DerivedKeys(db_key=db_key, attach_key=attach_key)


def encrypt_file(src: BinaryIO, dst: BinaryIO, key: bytes) -> None:
    """Encrypts a binary stream into another binary stream with AES-256-GCM.

    Output format:
        nonce (12 B) || ciphertext (N B) || tag (16 B)

    Streaming: memory bounded by `CHUNK_SIZE`. Suitable for attachments of
    any size.
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
    """Decrypts a `nonce||ct||tag`-format file to a destination stream.

    Needs a seekable file because the tag sits at the end (GCM requires
    the tag before verification can start). Not a restriction for
    attachments stored on disk.
    """
    size = src_path.stat().st_size
    if size < NONCE_LEN + TAG_LEN:
        raise ValueError(f"file too small to be an encrypted blob: {src_path}")
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
    """Generator that decrypts a blob on the fly in chunks. Ideal for HTTP streaming.

    Same input format as `decrypt_file` (`nonce(12)||ct||tag(16)`); the tag
    is read first (seek to the end), then the body is decrypted in chunks and
    finally closed with `finalize()` (which verifies the GCM tag).
    """
    size = src_path.stat().st_size
    if size < NONCE_LEN + TAG_LEN:
        raise ValueError(f"file too small to be an encrypted blob: {src_path}")
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
    """Encrypts a small in-memory blob. Useful for verification tokens."""
    nonce = os.urandom(NONCE_LEN)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
    enc = cipher.encryptor()
    ct = enc.update(data) + enc.finalize()
    return nonce + ct + enc.tag


def decrypt_bytes(blob: bytes, key: bytes) -> bytes:
    """Decrypts a small blob encrypted with `encrypt_bytes`."""
    if len(blob) < NONCE_LEN + TAG_LEN:
        raise ValueError("blob too small")
    nonce = blob[:NONCE_LEN]
    tag = blob[-TAG_LEN:]
    ct = blob[NONCE_LEN:-TAG_LEN]
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag))
    dec = cipher.decryptor()
    return dec.update(ct) + dec.finalize()
