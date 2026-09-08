"""What every namespaced accessor shares: the transport, and the parsing of a response."""

from typing import Any

from pydantic import BaseModel, SecretStr

from dirigent_client.schemas import Page
from dirigent_client.transport import Transport


class Resource:
    """One group of endpoints, bound to the connection they are called over."""

    def __init__(self, transport: Transport) -> None:
        """Bind the accessor to the instance its calls go to."""
        self._transport = transport

    async def _one[T: BaseModel](self, model: type[T], method: str, path: str, **kwargs: Any) -> T:
        """Make one request and read its body as the schema the endpoint answers with."""
        return model.model_validate(await self._transport.json(method, path, **kwargs))

    async def _many[T: BaseModel](self, model: type[T], method: str, path: str, **kwargs: Any) -> Page[T]:
        """Make one request and read its body as one page of the schema it answers with."""
        payload: dict[str, Any] = await self._transport.json(method, path, **kwargs)
        return Page(items=[model.model_validate(row) for row in payload["items"]], next=payload.get("next"))


def query(**values: object) -> dict[str, Any]:
    """Build a query string from the arguments a caller actually supplied."""
    return {name: value for name, value in values.items() if value is not None}


def request_body(schema: BaseModel) -> dict[str, Any]:
    """Render a request schema as the JSON body it is sent as.

    A field's wire spelling is its alias where it has one, which is how a body can carry a
    key that is a Python keyword. A secret field serialises to its mask everywhere else; this
    is the one place the value itself has to travel, so it is put back.
    """
    rendered = schema.model_dump(mode="json", by_alias=True)
    for name, value in schema:
        if isinstance(value, SecretStr):
            rendered[_wire_name(schema, name)] = value.get_secret_value()
    return rendered


def _wire_name(schema: BaseModel, name: str) -> str:
    """Name a field the way the body spells it."""
    field = type(schema).model_fields.get(name)
    if field is None:  # pragma: no cover - the name came from iterating the model itself
        return name
    return field.serialization_alias or field.alias or name
