"""Tests for envelope encryption of connection secrets."""

import pytest
from cryptography.fernet import Fernet
from pydantic import BaseModel, SecretStr

from dirigent_core.secrets import (
    REDACTED,
    SecretBox,
    SecretKeyMismatch,
    SecretKeyMissing,
    derive_key,
    dump_config,
    redact,
    secret_fields,
    split_secrets,
)


class ApiConnection(BaseModel):
    """A connection kind's config with two secret fields and two public ones."""

    base_url: str
    verify_tls: bool = True
    token: SecretStr
    password: SecretStr | None = None


@pytest.fixture
def box() -> SecretBox:
    """A box holding a real Fernet key."""
    return SecretBox(Fernet.generate_key().decode())


@pytest.fixture
def config() -> ApiConnection:
    """A connection config with both secret fields populated."""
    return ApiConnection(base_url="https://api.example", token=SecretStr("t0ken"), password=SecretStr("hunter2"))


def test_secret_fields_are_found_through_the_config_model() -> None:
    assert secret_fields(ApiConnection) == ["token", "password"]


def test_a_model_without_secrets_has_none() -> None:
    class Plain(BaseModel):
        host: str

    assert secret_fields(Plain) == []


def test_a_fernet_key_is_used_verbatim_and_a_passphrase_is_derived() -> None:
    generated = Fernet.generate_key()
    assert derive_key(generated.decode()) == generated
    derived = derive_key("a human passphrase")
    assert derived != b"a human passphrase"
    Fernet(derived)


def test_dump_config_reveals_secrets_for_sealing(config: ApiConnection) -> None:
    dumped = dump_config(config)
    assert dumped["token"] == "t0ken"
    assert dumped["password"] == "hunter2"
    assert dumped["base_url"] == "https://api.example"


def test_split_separates_public_columns_from_the_envelope(config: ApiConnection) -> None:
    public, secret = split_secrets(ApiConnection, dump_config(config))
    assert public == {"base_url": "https://api.example", "verify_tls": True}
    assert secret == {"token": "t0ken", "password": "hunter2"}


def test_redaction_masks_only_the_secret_fields(config: ApiConnection) -> None:
    masked = redact(ApiConnection, dump_config(config))
    assert masked == {
        "base_url": "https://api.example",
        "verify_tls": True,
        "token": REDACTED,
        "password": REDACTED,
    }


def test_redaction_leaves_an_unset_secret_alone() -> None:
    config = ApiConnection(base_url="https://api.example", token=SecretStr("t"))
    assert redact(ApiConnection, dump_config(config))["password"] is None


def test_a_config_round_trips_through_the_envelope(box: SecretBox, config: ApiConnection) -> None:
    public, envelope, key_id = box.encrypt_config(ApiConnection, config)
    assert "token" not in public
    assert envelope is not None
    assert key_id == box.key_id
    assert b"t0ken" not in envelope
    restored = box.decrypt_config(ApiConnection, public, envelope, key_id=key_id)
    assert restored.token.get_secret_value() == "t0ken"
    assert restored.password is not None
    assert restored.password.get_secret_value() == "hunter2"
    assert restored.base_url == "https://api.example"


def test_a_config_with_no_secrets_stores_no_envelope(box: SecretBox) -> None:
    class Plain(BaseModel):
        host: str

    public, envelope, key_id = box.encrypt_config(Plain, Plain(host="db"))
    assert public == {"host": "db"}
    assert envelope is None
    assert key_id is None
    assert box.decrypt_config(Plain, public, None).host == "db"


def test_a_wrong_key_fails_with_a_clear_error(config: ApiConnection) -> None:
    sealed_by = SecretBox(Fernet.generate_key().decode())
    _, envelope, key_id = sealed_by.encrypt_config(ApiConnection, config)
    other = SecretBox(Fernet.generate_key().decode())
    with pytest.raises(SecretKeyMismatch, match="cannot open this envelope") as raised:
        other.open(envelope, key_id=key_id)
    assert raised.value.key_id == key_id


def test_a_missing_key_fails_with_a_clear_error(config: ApiConnection) -> None:
    keyless = SecretBox(None)
    assert keyless.available is False
    with pytest.raises(SecretKeyMissing, match="DIRIGENT_SECRET_KEY"):
        keyless.encrypt_config(ApiConnection, config)
    with pytest.raises(SecretKeyMissing):
        keyless.open(b"whatever")


def test_a_keyless_box_still_opens_an_absent_envelope() -> None:
    assert SecretBox(None).open(None) == {}


def test_the_key_id_is_stable_and_never_the_key() -> None:
    material = Fernet.generate_key().decode()
    assert SecretBox(material).key_id == SecretBox(material).key_id
    key_id = SecretBox(material).key_id
    assert key_id is not None
    assert len(key_id) == 12
    assert key_id not in material
    assert SecretBox(None).key_id is None
