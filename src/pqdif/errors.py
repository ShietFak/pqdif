"""Public exceptions shared by the three API layers."""


class PqdifError(Exception):
    """Base class for library errors."""


class PqdifFormatError(PqdifError, ValueError):
    """An unsafe or malformed physical encoding."""

    def __init__(self, message: str, offset: int | None = None):
        self.offset = offset
        super().__init__(message if offset is None else f"{message} at byte {offset}")


class UnsupportedFeatureError(PqdifError, NotImplementedError):
    """An encoding that cannot safely be interpreted or rewritten."""


class ValidationError(PqdifError, ValueError):
    """An invalid or ambiguous logical structure."""
