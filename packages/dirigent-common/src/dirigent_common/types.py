"""The JSON shapes a document, a record and a wire body are all made of."""

from typing import Any

#: A JSON object, as a document's config, a block's output and a response body all are.
type JsonMap = dict[str, Any]

#: A JSON array.
type JsonList = list[Any]
