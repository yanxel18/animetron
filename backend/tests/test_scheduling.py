from datetime import UTC, datetime

import pytest

from app.services.scheduling.preview import preview_occurrences


def test_preview_returns_five_strictly_future_occurrences_with_local_offsets() -> None:
    occurrences = preview_occurrences(
        "*/15 * * * *",
        "Asia/Kathmandu",
        datetime(2026, 11, 14, 3, 45, tzinfo=UTC),
    )

    assert [occurrence.local_time.isoformat() for occurrence in occurrences] == [
        f"2026-11-14T{time}:00+05:45"
        for time in ("09:45", "10:00", "10:15", "10:30", "10:45")
    ]
    assert occurrences[0].due_at == datetime(2026, 11, 14, 4, tzinfo=UTC)
    assert occurrences[0].slot_key == "Asia/Kathmandu:2026-11-14T09:45"


def test_restricted_day_of_month_and_weekday_use_or_not_and() -> None:
    occurrences = preview_occurrences(
        "0 9 1 * MON", "UTC", datetime(2026, 10, 31, tzinfo=UTC)
    )

    assert [occurrence.local_time.day for occurrence in occurrences] == [
        1,
        2,
        9,
        16,
        23,
    ]


def test_spring_forward_gap_is_skipped_not_shifted() -> None:
    occurrences = preview_occurrences(
        "30 2 * * *",
        "America/New_York",
        datetime(2026, 3, 8, 5, tzinfo=UTC),
    )

    assert occurrences[0].local_time.isoformat() == "2026-03-09T02:30:00-04:00"
    assert occurrences[0].due_at == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)


def test_or_matching_keeps_weekdays_when_the_restricted_date_cannot_exist() -> None:
    occurrences = preview_occurrences(
        "0 0 31 FEB MON", "UTC", datetime(2026, 2, 1, tzinfo=UTC)
    )

    assert [occurrence.due_at.isoformat() for occurrence in occurrences] == [
        "2026-02-02T00:00:00+00:00",
        "2026-02-09T00:00:00+00:00",
        "2026-02-16T00:00:00+00:00",
        "2026-02-23T00:00:00+00:00",
        "2027-02-01T00:00:00+00:00",
    ]


def test_fall_back_returns_only_the_earlier_occurrence() -> None:
    occurrences = preview_occurrences(
        "30 1 * * *",
        "America/New_York",
        datetime(2026, 11, 1, 4, tzinfo=UTC),
    )

    assert occurrences[0].due_at == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert occurrences[0].local_time.isoformat() == "2026-11-01T01:30:00-04:00"
    assert occurrences[1].due_at == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
    assert len({occurrence.slot_key for occurrence in occurrences}) == 5


@pytest.mark.parametrize("hour,minute", [(5, 45), (6, 0), (6, 15), (6, 30)])
def test_preview_during_fold_does_not_offer_an_already_missed_earlier_slot(
    hour: int, minute: int
) -> None:
    occurrences = preview_occurrences(
        "30 1 * * *",
        "America/New_York",
        datetime(2026, 11, 1, hour, minute, tzinfo=UTC),
    )

    assert occurrences[0].due_at == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)


def test_non_hour_dst_transition_uses_earlier_local_slot() -> None:
    occurrences = preview_occurrences(
        "45 1 * * *",
        "Australia/Lord_Howe",
        datetime(2026, 4, 4, 13, tzinfo=UTC),
    )

    assert occurrences[0].due_at == datetime(2026, 4, 4, 14, 45, tzinfo=UTC)
    assert occurrences[0].local_time.isoformat() == "2026-04-05T01:45:00+11:00"
    assert occurrences[1].local_time.isoformat() == "2026-04-06T01:45:00+10:30"


def test_skipped_calendar_date_has_no_slot() -> None:
    occurrences = preview_occurrences(
        "0 12 * * *",
        "Pacific/Apia",
        datetime(2011, 12, 29, 23, tzinfo=UTC),
    )

    assert occurrences[0].local_time.isoformat() == "2011-12-31T12:00:00+14:00"


def test_leap_day_preview_can_cross_a_non_leap_century() -> None:
    occurrences = preview_occurrences(
        "0 0 29 FEB *", "UTC", datetime(2096, 3, 1, tzinfo=UTC)
    )

    assert [occurrence.due_at.year for occurrence in occurrences] == [
        2104,
        2108,
        2112,
        2116,
        2120,
    ]


@pytest.mark.parametrize(
    "expression",
    [
        "@daily",
        "* * * * * *",
        "* * * * * 0 2026",
        "0 25 * * *",
        "0 0 L * *",
        "0 0 * * SUN#2",
        "H * * * *",
        "0 0 31 FEB *",
    ],
)
def test_invalid_or_unapproved_cron_fails_explicitly(expression: str) -> None:
    with pytest.raises(ValueError, match="cron|occurrence"):
        preview_occurrences(expression, "UTC", datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize("time_zone", ["", "Not/AZone", "../UTC", "/UTC"])
def test_non_iana_time_zone_fails_explicitly(time_zone: str) -> None:
    with pytest.raises(ValueError, match="IANA"):
        preview_occurrences("0 0 * * *", time_zone, datetime(2026, 1, 1, tzinfo=UTC))


def test_naive_cursor_is_rejected_instead_of_using_the_host_time_zone() -> None:
    with pytest.raises(ValueError, match="aware"):
        preview_occurrences("0 0 * * *", "UTC", datetime(2026, 1, 1))
