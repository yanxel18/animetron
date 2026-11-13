import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, CroniterBadDateError, croniter

_CRON_NAMES = frozenset(
    [
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
        "sun",
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
    ]
)


@dataclass(frozen=True)
class ScheduleOccurrence:
    local_time: datetime
    due_at: datetime
    slot_key: str


def preview_occurrences(
    expression: str, time_zone: str, after: datetime
) -> tuple[ScheduleOccurrence, ...]:
    if after.tzinfo is None or after.utcoffset() is None:
        raise ValueError("Schedule preview requires an aware cursor")
    if (
        len(expression.split()) != 5
        or re.fullmatch(r"[A-Za-z0-9*,/\s-]+", expression) is None
        or not set(re.findall(r"[a-z]+", expression.lower())) <= _CRON_NAMES
    ):
        raise ValueError("Invalid five-field cron expression")
    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Schedule time zone must be an explicit IANA zone") from None

    after_utc = after.astimezone(UTC)
    wall_cursor = after_utc.astimezone(zone).replace(tzinfo=None)
    try:
        # Iterate wall-clock cron candidates, then enforce our gap/fold policy
        # instead of inheriting croniter's timezone-aware DST adjustments.
        iterator = croniter(
            expression, wall_cursor, day_or=True, max_years_between_matches=50
        )
    except CroniterBadCronError:
        raise ValueError("Invalid five-field cron expression") from None

    occurrences: list[ScheduleOccurrence] = []
    while len(occurrences) < 5:
        try:
            wall_time = iterator.get_next(datetime)
        except (CroniterBadDateError, OverflowError):
            raise ValueError(
                "No cron occurrence within the supported search range"
            ) from None
        if wall_time.year > wall_cursor.year + 50:
            raise ValueError("No cron occurrence within the supported search range")
        local_time = wall_time.replace(tzinfo=zone, fold=0)
        due_at = local_time.astimezone(UTC)
        if due_at.astimezone(zone).replace(tzinfo=None) != wall_time:
            continue
        if due_at <= after_utc:
            continue
        occurrences.append(
            ScheduleOccurrence(
                local_time=local_time,
                due_at=due_at,
                slot_key=f"{time_zone}:{wall_time.isoformat(timespec='minutes')}",
            )
        )
    return tuple(occurrences)
