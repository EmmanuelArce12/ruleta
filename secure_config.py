from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _normalized_key_material() -> bytes:
    secret = os.environ.get("DEBO_CREDENTIALS_KEY") or os.environ.get("FLASK_SECRET_KEY")
    if not secret:
        raise RuntimeError("Falta DEBO_CREDENTIALS_KEY en el entorno para cifrar credenciales DEBO.")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet() -> Fernet:
    return Fernet(_normalized_key_material())


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    return get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
