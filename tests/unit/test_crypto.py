import pytest
from cryptography.fernet import Fernet

from app.core import crypto
from app.core.config import get_settings


def test_credential_round_trip_and_key_rotation(monkeypatch):
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    secret = {"webhook_url": "https://discord.com/api/webhooks/1/abc", "guild_id": "9"}

    monkeypatch.setattr(get_settings(), "credential_encryption_keys", [old_key])
    old_token, old_version = crypto.encrypt_credential(secret)
    assert b"discord.com" not in old_token
    assert crypto.decrypt_credential(old_token) == secret

    # 輪替：新金鑰放最前面，舊資料仍可解密，新資料改用新金鑰加密
    monkeypatch.setattr(get_settings(), "credential_encryption_keys", [new_key, old_key])
    assert crypto.decrypt_credential(old_token) == secret
    new_token, new_version = crypto.encrypt_credential(secret)
    assert new_version == old_version + 1

    monkeypatch.setattr(get_settings(), "credential_encryption_keys", [new_key])
    assert crypto.decrypt_credential(new_token) == secret
    with pytest.raises(crypto.CredentialKeyError):
        crypto.decrypt_credential(old_token)


@pytest.mark.parametrize("keys", [[], ["not-a-fernet-key"]])
def test_encrypt_requires_configured_key(monkeypatch, keys):
    monkeypatch.setattr(get_settings(), "credential_encryption_keys", keys)

    with pytest.raises(crypto.CredentialKeyError):
        crypto.encrypt_credential({"webhook_url": "https://discord.com/api/webhooks/1/abc"})
