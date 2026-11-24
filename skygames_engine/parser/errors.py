from __future__ import annotations


class FileValidationError(ValueError):
    """Raised when an uploaded file cannot be scored. ``code`` is stable and
    machine-readable (for the API / UI); ``message`` is for humans."""

    def __init__(self, code: str, message: str, hint: str = ""):
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(f"[{code}] {message}" + (f" Hint: {hint}" if hint else ""))

    def to_dict(self):
        return {"code": self.code, "message": self.message, "hint": self.hint}
