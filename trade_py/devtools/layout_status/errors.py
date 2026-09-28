"""Stable, payload-free errors for read-only layout diagnostics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutStatusError:
    code: str
    message: str
    record: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "record": self.record,
        }


class LayoutStatusInvalid(RuntimeError):
    def __init__(self, error: LayoutStatusError) -> None:
        super().__init__(error.message)
        self.error = error


def invalid(code: str, message: str, *, record: str | None = None) -> LayoutStatusInvalid:
    return LayoutStatusInvalid(LayoutStatusError(code=code, message=message, record=record))


__all__ = ["LayoutStatusError", "LayoutStatusInvalid", "invalid"]
