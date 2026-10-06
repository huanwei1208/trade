from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

__all__ = ["Deadline", "DurationMs", "UtcInstant"]

_UTC_INSTANT_PATTERN = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"\.(?P<microsecond>[0-9]{6})Z",
    re.ASCII,
)


@dataclass(frozen=True, slots=True)
class UtcInstant:
    value: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.value, datetime):
            raise TypeError("UTC instant value must be datetime")
        if self.value.tzinfo is None or self.value.utcoffset() != timedelta(0):
            raise ValueError("UTC instant must be timezone-aware with an exact zero offset")

    @classmethod
    def from_wire(cls, value: str) -> UtcInstant:
        if not isinstance(value, str):
            raise TypeError("UTC instant wire value must be str")
        match = _UTC_INSTANT_PATTERN.fullmatch(value)
        if match is None:
            raise ValueError("UTC instant must use YYYY-MM-DDTHH:MM:SS.ffffffZ")
        fields = {name: int(component) for name, component in match.groupdict().items()}
        if not 0 <= fields["second"] <= 59:
            raise ValueError("UTC instant seconds must be in 00..59")
        try:
            instant = datetime(
                fields["year"],
                fields["month"],
                fields["day"],
                fields["hour"],
                fields["minute"],
                fields["second"],
                fields["microsecond"],
                tzinfo=timezone.utc,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("UTC instant contains an invalid calendar value") from error
        return cls(instant)

    def to_wire(self) -> str:
        value = self.value
        return (
            f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
            f"T{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
            f".{value.microsecond:06d}Z"
        )


@dataclass(frozen=True, slots=True)
class DurationMs:
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or isinstance(self.value, bool):
            raise TypeError("duration must be an integer number of milliseconds")
        if not 1 <= self.value <= 86_400_000:
            raise ValueError("duration must be in 1..86,400,000 milliseconds")


@dataclass(frozen=True, slots=True)
class Deadline:
    wall_clock_expires_at: UtcInstant
    monotonic_expires_at: float

    def __post_init__(self) -> None:
        if not isinstance(self.wall_clock_expires_at, UtcInstant):
            raise TypeError("deadline wall-clock evidence must be UtcInstant")
        if (
            not isinstance(self.monotonic_expires_at, (int, float))
            or isinstance(self.monotonic_expires_at, bool)
            or not math.isfinite(self.monotonic_expires_at)
        ):
            raise TypeError("deadline monotonic expiry must be a finite number")

    @classmethod
    def from_duration(
        cls,
        *,
        wall_clock_started_at: UtcInstant,
        monotonic_started_at: float,
        duration: DurationMs,
    ) -> Deadline:
        if not isinstance(duration, DurationMs):
            raise TypeError("deadline duration must be DurationMs")
        milliseconds = duration.value
        try:
            expires_at = wall_clock_started_at.value + timedelta(milliseconds=milliseconds)
        except OverflowError as error:
            raise ValueError("deadline wall-clock expiry exceeds the supported range") from error
        return cls(
            wall_clock_expires_at=UtcInstant(expires_at),
            monotonic_expires_at=monotonic_started_at + milliseconds / 1_000,
        )

    def remaining_ms(self, monotonic_now: float) -> int:
        if (
            not isinstance(monotonic_now, (int, float))
            or isinstance(monotonic_now, bool)
            or not math.isfinite(monotonic_now)
        ):
            raise TypeError("monotonic observation must be a finite number")
        return max(0, math.ceil((self.monotonic_expires_at - monotonic_now) * 1_000))

    def is_expired(self, monotonic_now: float) -> bool:
        return self.remaining_ms(monotonic_now) == 0
