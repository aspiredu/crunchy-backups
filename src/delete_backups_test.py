from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import time_machine

from src.create_test_backups import get_test_dates
from src.delete_backups import (
    meets_retention_policy,
    saturdays_for_the_past_three_years,
)

utc_tz = ZoneInfo("UTC")


@time_machine.travel(datetime(2020, 1, 1, tzinfo=utc_tz))
def test_saturdays_for_the_past_three_years():
    today = date.today()
    saturdays = list(sorted(saturdays_for_the_past_three_years(today)))
    assert len(saturdays) == 72
    assert saturdays[0] == date(2017, 1, 7)
    assert saturdays[-1] == date(2019, 12, 21)

    redo = list(sorted(saturdays_for_the_past_three_years(today - timedelta(days=1))))
    assert saturdays == redo


@time_machine.travel(datetime(2020, 1, 1, tzinfo=utc_tz))
def test_meets_retention_policy():
    retain_dates = list(
        sorted((d for d in get_test_dates() if meets_retention_policy(d)), reverse=True)
    )
    assert len(retain_dates) == 72
    # Do some quick checks on the first 64 dates since they are easy
    # to guess the next date. The first saturday of each month is
    # less easy write a loop for.
    for value in retain_dates:
        assert value.weekday() == 5

    assert retain_dates[0] == date(2019, 12, 21)
    assert retain_dates[1] == date(2019, 12, 7)
    assert retain_dates[-2] == date(2017, 1, 21)
    assert retain_dates[-1] == date(2017, 1, 7)
