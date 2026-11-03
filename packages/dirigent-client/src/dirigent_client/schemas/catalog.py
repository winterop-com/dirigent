"""The block catalog: what an instance can run, and the schemas a form is built from."""

import hashlib
import json
from enum import StrEnum
from typing import cast

from pydantic import BaseModel, Field, JsonValue

from dirigent_common import API_VERSION, CredentialForm, JsonMap

#: The humane string formats a field is described by, in place of the ``string`` they are.
HUMANE_FORMATS = {"humane-duration": "duration", "humane-size": "size"}


class BlockKind(StrEnum):
    """Which block surface a catalog entry describes."""

    OPERATOR = "operator"
    """Does work; may finish synchronously or return a remote handle."""

    SENSOR = "sensor"
    """Waits for the world through durable, scheduled pokes."""


class BlockEntry(BaseModel):
    """One block in the catalog, with the schemas a form is built from."""

    id: str
    kind: BlockKind
    summary: str
    group: str
    plugin: str
    idempotent: bool = False
    local_execution: bool = False
    default_poll_seconds: float | None = None
    default_deadline_seconds: float | None = None
    config_schema: JsonMap = Field(default_factory=dict)
    output_schema: JsonMap = Field(default_factory=dict)


class SurfaceEntry(BaseModel):
    """One catalog entry for a non-block surface: a scheme, a notifier, a connection kind."""

    id: str
    plugin: str
    config_schema: JsonMap = Field(default_factory=dict)
    secret_fields: list[str] = Field(default_factory=list[str])
    """Which config fields this surface declares secret, so a form draws them write-only."""

    mark: str | None = None
    """The ``d`` of one SVG path on a 24-unit grid this surface's kind is drawn by, where it
    declares one. Monochrome: a screen fills it in the ink it draws every other mark in."""

    credential_forms: list[CredentialForm] = Field(default_factory=list[CredentialForm])
    """The ways a connection kind authenticates when it takes one of several, each naming its fields."""

    credential_required: bool = False
    """Whether a connection of this kind needs one of ``credential_forms`` to work."""


class ConnectionKindField(BaseModel):
    """One config field of a connection kind, as ``dg connection create --set`` and an agent write it."""

    name: str
    type: str
    """What the value is, in JSON Schema's words, or ``duration`` and ``size`` for a humane one."""

    secret: bool = False
    """Sealed at rest and never read back; an agent never passes one."""

    required: bool = False
    default: JsonValue = None
    """The value an unset field takes, where ``has_default`` says there is one; it may itself be null."""

    has_default: bool = False
    choices: list[JsonValue] | None = None
    """The values the field takes, where it is one of a fixed set."""

    credential_form: str | None = None
    """The code of the credential form this field belongs to, where the kind declares forms."""

    description: str | None = None


class ConnectionKindEntry(BaseModel):
    """One connection kind with its fields: which are secret, which required, their defaults, its credential forms."""

    id: str
    plugin: str
    description: str | None = None
    fields: list[ConnectionKindField] = Field(default_factory=list[ConnectionKindField])
    credential_forms: list[CredentialForm] = Field(default_factory=list[CredentialForm])
    """The ways the kind authenticates when it takes one of several, each naming its fields."""

    credential_required: bool = False
    """Whether a connection of this kind needs one of ``credential_forms`` to work."""

    @classmethod
    def of(cls, surface: "SurfaceEntry") -> "ConnectionKindEntry":
        """Read a connection kind's catalog entry as its fields, in the order its schema declares them."""
        schema = surface.config_schema
        properties = cast("dict[str, JsonMap]", schema.get("properties") or {})
        required = set(cast("list[str]", schema.get("required") or []))
        definitions = cast("dict[str, JsonMap]", schema.get("$defs") or {})
        forms = {field: form.code for form in surface.credential_forms for field in form.fields}
        described = schema.get("description")
        return cls(
            id=surface.id,
            plugin=surface.plugin,
            description=described if isinstance(described, str) else None,
            fields=[
                ConnectionKindField(
                    name=name,
                    type=_type_of(body, definitions),
                    secret=name in surface.secret_fields,
                    required=name in required,
                    default=body.get("default"),
                    has_default="default" in body,
                    choices=_choices_of(body, definitions),
                    credential_form=forms.get(name),
                    description=_text(body.get("description")),
                )
                for name, body in properties.items()
            ],
            credential_forms=surface.credential_forms,
            credential_required=surface.credential_required,
        )


def _text(value: object) -> str | None:
    """Answer a schema's string, or None for anything else."""
    return value if isinstance(value, str) else None


def _resolved(body: JsonMap, definitions: dict[str, JsonMap]) -> JsonMap:
    """Follow a local ``$ref`` to the definition it names, or answer the body as it is."""
    reference = body.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
        return body
    beside = {key: value for key, value in body.items() if key != "$ref"}
    return {**definitions.get(reference.removeprefix("#/$defs/"), {}), **beside}


def _type_of(body: JsonMap, definitions: dict[str, JsonMap]) -> str:
    """Name what a property's value is, leaving out the null an optional field also takes."""
    body = _resolved(body, definitions)
    variants = cast("list[JsonMap]", body.get("anyOf") or [])
    if variants:
        named = [_type_of(variant, definitions) for variant in variants if variant.get("type") != "null"]
        return " or ".join(dict.fromkeys(named)) or "null"
    shown = body.get("format")
    if isinstance(shown, str) and shown in HUMANE_FORMATS:
        return HUMANE_FORMATS[shown]
    if "enum" in body:
        return "enum"
    declared = body.get("type")
    if declared == "array":
        items = body.get("items")
        return f"array of {_type_of(cast('JsonMap', items), definitions)}" if isinstance(items, dict) else "array"
    if isinstance(declared, list):
        return " or ".join(str(one) for one in cast("list[object]", declared) if one != "null")
    return str(declared) if declared else "any"


def _choices_of(body: JsonMap, definitions: dict[str, JsonMap]) -> list[JsonValue] | None:
    """List the values an enum property takes, through a reference or an optional's variants."""
    body = _resolved(body, definitions)
    listed = body.get("enum")
    if isinstance(listed, list):
        return list(cast("list[JsonValue]", listed))
    for variant in cast("list[JsonMap]", body.get("anyOf") or []):
        found = _choices_of(variant, definitions)
        if found is not None:
            return found
    return None


class SourceEntry(BaseModel):
    """One source kind in the catalog: where an input enters a pipeline, and what it hands on."""

    kind: str
    """What a document writes as ``source.kind``."""

    plugin: str
    summary: str
    hosting: str
    """Who takes the kind's inputs: ``received`` by the server, ``polled`` or ``held`` by a worker."""

    replies: bool = False
    """Whether a reply node may answer an input of this kind."""

    config_schema: JsonMap = Field(default_factory=dict)
    """The fields a source node of this kind writes beside ``kind``."""

    output_schema: JsonMap = Field(default_factory=dict)
    """The input a source node of this kind hands the step after it."""

    secret_fields: list[str] = Field(default_factory=list[str])
    mark: str | None = None
    """The ``d`` of one SVG path on a 24-unit grid this kind is drawn by, where it declares one."""


class Catalog(BaseModel):
    """The host's merged view of every contribution."""

    api_version: int = API_VERSION
    plugins: list[str] = Field(default_factory=list[str])
    blocks: list[BlockEntry] = Field(default_factory=list[BlockEntry])
    storage_schemes: list[SurfaceEntry] = Field(default_factory=list[SurfaceEntry])
    notifiers: list[SurfaceEntry] = Field(default_factory=list[SurfaceEntry])
    connection_kinds: list[SurfaceEntry] = Field(default_factory=list[SurfaceEntry])
    sources: list[SourceEntry] = Field(default_factory=list[SourceEntry])
    """The source kinds a source node may write."""

    def block(self, block_id: str) -> BlockEntry | None:
        """Find one catalog entry by block id."""
        return next((entry for entry in self.blocks if entry.id == block_id), None)

    def source(self, kind: str) -> SourceEntry | None:
        """Find one source kind by the ``kind`` a document writes."""
        return next((entry for entry in self.sources if entry.kind == kind), None)

    @property
    def digest(self) -> str:
        """Hash the catalog, so a worker registry row can prove code parity across nodes."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"
