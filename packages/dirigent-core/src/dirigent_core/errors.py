"""The base every refusal the API answers with a problem document derives from."""


class DomainError(Exception):
    """A refusal a caller can act on, carrying the HTTP status the API answers it with."""

    status: int = 422

    @property
    def problems(self) -> list[str]:
        """The list a refusal carries beside its sentence, empty when it carries none."""
        return []
