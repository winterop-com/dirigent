"""The base every refusal the API answers with a problem document derives from."""

from collections.abc import Iterable
from typing import Any, ClassVar

from dirigent_common import Issue, JsonMap, Message


class DomainError(Exception):
    """A refusal a caller can act on, carrying its code, its params and the status to answer."""

    status: int = 422

    message: ClassVar[Message]
    """The one message a subclass that refuses for one reason renders; a subclass that
    refuses for several is raised with the message that applies instead."""

    def __init__(self, message: Message | None = None, /, *, problems: Iterable[Issue] = (), **params: Any) -> None:
        """Render the message this refusal carries, or the one its class always renders."""
        chosen = type(self).message if message is None else message
        self.code = chosen.code
        self.params: JsonMap = dict(params)
        self._problems = list(problems)
        super().__init__(chosen.render(**params))

    @property
    def problems(self) -> list[Issue]:
        """The list a refusal carries beside its sentence, empty when it carries none."""
        return list(self._problems)
