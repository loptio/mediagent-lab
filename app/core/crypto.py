"""平台憑證加解密：MultiFernet，金鑰來自環境變數，與資料庫分開保存（NFR-02、NFR-06）。

憑證是一份 JSON，內容由各平台的 Adapter 自己定義（foundation-plan D-13）；
其他程式不解讀，也不得把解密後的內容寫進 Log、錯誤訊息或 API 回應。
"""

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import get_settings


class CredentialKeyError(RuntimeError):
    """加密金鑰沒有設定、格式錯誤，或無法解開既有資料。"""


def _keys() -> list[str]:
    keys = get_settings().credential_encryption_keys
    if not keys:
        raise CredentialKeyError("CREDENTIAL_ENCRYPTION_KEYS is not configured")
    return keys


def _fernet() -> MultiFernet:
    try:
        return MultiFernet([Fernet(key) for key in _keys()])
    except ValueError as exc:
        raise CredentialKeyError("CREDENTIAL_ENCRYPTION_KEYS contains an invalid key") from exc


def encrypt_credential(data: dict[str, Any]) -> tuple[bytes, int]:
    """加密憑證，回傳（密文, 金鑰版本）。一律用第一把金鑰加密；版本 = 目前設定的金鑰數。"""
    token = _fernet().encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    return token, len(_keys())


def decrypt_credential(token: bytes) -> dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(bytes(token)))
    except InvalidToken as exc:
        raise CredentialKeyError("credential cannot be decrypted with the configured keys") from exc
