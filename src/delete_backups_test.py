from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import time_machine

from src.create_test_backups import get_test_dates
from src.delete_backups import (
    first_saturdays_of_month_year1_to_year3,
    is_saturday,
    meets_retention_policy,
    saturdays_for_the_past_year,
)

utc_tz = ZoneInfo("UTC")


def test_is_saturday():
    assert not is_saturday(date(2021, 1, 8))
    assert is_saturday(date(2021, 1, 9))
    assert not is_saturday(date(2021, 1, 10))


@time_machine.travel(datetime(2020, 1, 1, tzinfo=utc_tz))
def test_saturdays_for_the_past_year():
    saturdays = list(sorted(saturdays_for_the_past_year()))
    assert len(saturdays) == 52
    assert saturdays[0] == date(2019, 1, 5)
    assert saturdays[-1] == date(2019, 12, 28)


@time_machine.travel(datetime(2020, 1, 1, tzinfo=utc_tz))
def test_first_saturdays_of_month_year1_to_year3():
    saturdays = list(sorted(first_saturdays_of_month_year1_to_year3()))
    assert len(saturdays) == 24
    assert saturdays[0] == date(2017, 1, 7)
    assert saturdays[-1] == date(2018, 12, 1)


@time_machine.travel(datetime(2020, 1, 1, tzinfo=utc_tz))
def test_meets_retention_policy():
    today = date.today()
    retain_dates = list(
        sorted((d for d in get_test_dates() if meets_retention_policy(d)), reverse=True)
    )
    # Do some quick checks on the first 64 dates since they are easy
    # to guess the next date. The first saturday of each month is
    # less easy write a loop for.
    for i in range(14):
        assert (today - retain_dates[i]) == timedelta(days=i)
    for i in range(50):
        assert (today - retain_dates[i + 14]) == timedelta(days=7 * i + 14 + 4)
    # confirm it appears to be a weekly change
    assert retain_dates[14] == date(2019, 12, 14)
    assert retain_dates[15] == date(2019, 12, 7)
    # Confirm that it changes from a weekly to a monthly change
    assert retain_dates[64] == date(2018, 12, 1)
    assert retain_dates[65] == date(2018, 11, 3)
    # Check the last elements are still monthly.
    assert retain_dates[-2] == date(2017, 2, 4)
    assert retain_dates[-1] == date(2017, 1, 7)
