"""
Шифрування HD-мнемоніка для зберігання в БД.

Використовується симетричне шифрування Fernet (AES-128 в режимі CBC + HMAC-SHA256
для перевірки цілісності). Ключ шифрування (MNEMONIC_ENC_KEY) зберігається ТІЛЬКИ
в backend/.env і НІКОЛИ не потрапляє в базу даних. Тому навіть маючи повний дамп
MongoDB, сторонні особи не зможуть розшифрувати мнемонік без цього ключа.

Формат у БД: колекція `system`, документ `_id="wallet"`, поле `mnemonic_enc`
містить base64-рядок Fernet-токена.
"""
import os
from cryptography.fernet import Fernet


def get_enc_key() -> bytes:
    key = os.environ.get("MNEMONIC_ENC_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "MNEMONIC_ENC_KEY не заданий у backend/.env — неможливо "
            "зашифрувати/розшифрувати мнемонік"
        )
    return key.encode("utf-8")


def encrypt_mnemonic(mnemonic: str) -> str:
    """Зашифрувати мнемонік → base64 Fernet-токен (для зберігання в БД)."""
    f = Fernet(get_enc_key())
    return f.encrypt(mnemonic.encode("utf-8")).decode("utf-8")


def decrypt_mnemonic(token: str) -> str:
    """Розшифрувати Fernet-токен з БД → відкритий мнемонік."""
    f = Fernet(get_enc_key())
    return f.decrypt(token.encode("utf-8")).decode("utf-8")
