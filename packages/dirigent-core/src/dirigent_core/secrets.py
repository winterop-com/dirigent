"""Envelope encryption for connection credentials.

A connection kind's ``config_model`` says which fields are secret by typing them
``SecretStr``: the same declaration that makes the API redact a field makes the engine
encrypt it. Only those fields go into the envelope; the rest stay queryable JSON on the row.
"""

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, SecretStr

from dirigent_common import JsonMap
from dirigent_core.errors import DomainError

REDACTED = "***"

#: The key identifier is stored beside an envelope, so a rotation can tell which key sealed
#: a row without trying to decrypt it.
KEY_ID_LENGTH = 12


class SecretError(DomainError):
    """Any failure in the secrets layer."""

    status = 409


class SecretKeyMissing(SecretError):
    """A secret had to be sealed or opened but the instance has no key configured."""

    def __init__(self) -> None:
        """Say exactly which variable to set, and how to generate a key."""
        super().__init__(
            "no secret key is configured: set DIRIGENT_SECRET_KEY before storing or reading "
            "connection secrets (generate one with `dg secret-key`)"
        )


class EmptySecret(SecretError):
    """A required secret field was given an empty value, which is not a credential."""

    def __init__(self, fields: list[str]) -> None:
        """Name the fields that came in empty."""
        super().__init__(f"{', '.join(fields)} cannot be stored empty: a required secret needs a value")
        self.fields = fields


class SecretKeyMismatch(SecretError):
    """An envelope could not be opened with the configured key."""

    def __init__(self, key_id: str | None) -> None:
        """Name the key that sealed the envelope."""
        sealed_by = f" sealed by key {key_id}" if key_id else ""
        super().__init__(
            f"the configured DIRIGENT_SECRET_KEY cannot open this envelope{sealed_by}: "
            "either the key changed or the row belongs to another instance"
        )
        self.key_id = key_id


def generate_key() -> str:
    """Mint a key for DIRIGENT_SECRET_KEY."""
    return Fernet.generate_key().decode()


def derive_key(material: str) -> bytes:
    """Turn configured key material into a Fernet key, accepting a passphrase as well.

    A Fernet key passes through untouched; anything else is hashed into a valid 32-byte key.
    """
    candidate = material.encode()
    try:
        Fernet(candidate)
    except (ValueError, TypeError):
        return base64.urlsafe_b64encode(hashlib.sha256(candidate).digest())
    return candidate


def key_id_for(key: bytes) -> str:
    """Derive a short, non-reversible identifier for a key, safe to store in the clear."""
    return hashlib.sha256(key).hexdigest()[:KEY_ID_LENGTH]


def secret_fields(model: type[BaseModel]) -> list[str]:
    """List the field names a config model declares as secret by typing them SecretStr."""
    return [name for name, field in model.model_fields.items() if _is_secret(field.annotation)]


def _is_secret(annotation: object) -> bool:
    """Report whether an annotation is SecretStr, including as an optional or a union member."""
    if annotation is SecretStr:
        return True
    arguments = getattr(annotation, "__args__", ())
    return any(argument is SecretStr for argument in arguments)


def split_secrets(model: type[BaseModel], config: JsonMap) -> tuple[JsonMap, JsonMap]:
    """Split a validated config into the public part and the part that must be sealed.

    A secret field with no value stays public as a null, so the envelope holds exactly the
    secrets that exist and a read can tell a stored credential from an empty field.
    """
    secret_names = set(secret_fields(model))
    public = {name: value for name, value in config.items() if name not in secret_names or value is None}
    secret = {name: value for name, value in config.items() if name in secret_names and value is not None}
    return public, secret


def unset_empty_secrets(model: type[BaseModel], config: JsonMap) -> JsonMap:
    """Return a config in which every secret field left empty is unset rather than sealed.

    An empty value is nobody's credential. Sealing one would store a secret that every read
    afterwards reports as set, so an optional secret given nothing stays unset; a required
    secret has no unset state to fall back to, so an empty value there is refused.
    """
    empty = sorted(name for name in secret_fields(model) if config.get(name) == "")
    required = [name for name in empty if model.model_fields[name].is_required()]
    if required:
        raise EmptySecret(required)
    return {name: (None if name in empty else value) for name, value in config.items()}


def redact(model: type[BaseModel], config: JsonMap) -> JsonMap:
    """Replace every secret field's value with the redaction marker, for display."""
    secret_names = set(secret_fields(model))
    return {name: (REDACTED if name in secret_names and value is not None else value) for name, value in config.items()}


def dump_config(config: BaseModel) -> JsonMap:
    """Serialize a connection config with secrets revealed, ready to be split and sealed."""
    dumped: JsonMap = json.loads(config.model_dump_json())
    for name in secret_fields(type(config)):
        value = getattr(config, name, None)
        dumped[name] = value.get_secret_value() if isinstance(value, SecretStr) else value
    return dumped


class SecretBox:
    """Seals and opens the secret half of a connection config with the instance key."""

    def __init__(self, key_material: str | None) -> None:
        """Bind the box to the configured key, or to no key at all."""
        self._key = derive_key(key_material) if key_material else None
        self.key_id = key_id_for(self._key) if self._key else None

    @property
    def available(self) -> bool:
        """Report whether this instance can seal or open secrets at all."""
        return self._key is not None

    def _fernet(self) -> Fernet:
        """Return the cipher, refusing clearly when the instance has no key."""
        if self._key is None:
            raise SecretKeyMissing
        return Fernet(self._key)

    def seal(self, secret: JsonMap) -> bytes:
        """Encrypt the secret half of a config."""
        payload = json.dumps(secret, sort_keys=True, separators=(",", ":")).encode()
        return self._fernet().encrypt(payload)

    def open(self, envelope: bytes | None, *, key_id: str | None = None) -> JsonMap:
        """Decrypt an envelope back into the secret half of a config."""
        if envelope is None:
            return {}
        try:
            payload = self._fernet().decrypt(envelope)
        except InvalidToken as error:
            raise SecretKeyMismatch(key_id) from error
        opened: JsonMap = json.loads(payload)
        return opened

    def encrypt_config(self, model: type[BaseModel], config: BaseModel) -> tuple[JsonMap, bytes | None, str | None]:
        """Split a config into its public columns and its sealed envelope, ready to store.

        A secret field left empty is stored unset, so nothing seals an empty credential.
        """
        public, secret = split_secrets(model, unset_empty_secrets(model, dump_config(config)))
        if not secret:
            return public, None, None
        return public, self.seal(secret), self.key_id

    def decrypt_config[C: BaseModel](
        self,
        model: type[C],
        public: JsonMap,
        envelope: bytes | None,
        *,
        key_id: str | None = None,
    ) -> C:
        """Recombine a stored connection and validate it against its model."""
        merged: dict[str, Any] = {**public, **self.open(envelope, key_id=key_id)}
        return model.model_validate(merged)
