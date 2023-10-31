from datetime import datetime

from dateutil import relativedelta, rrule


def is_valid_saturday(value) -> bool:
    """
    Determine if date is the first or third Saturday of the month.
    """
    if isinstance(value, datetime):
        value = value.date()
    month_start = value.replace(day=1)
    month_end = month_start + relativedelta.relativedelta(months=1)
    saturday_ruleset = rrule.rruleset()
    saturday_ruleset.rrule(
        rrule.rrule(rrule.MONTHLY, byweekday=rrule.SA(1), dtstart=month_start, until=month_end)
    )
    saturday_ruleset.rrule(
        rrule.rrule(rrule.MONTHLY, byweekday=rrule.SA(3), dtstart=month_start, until=month_end)
    )
    return value in {d.date() for d in saturday_ruleset}
