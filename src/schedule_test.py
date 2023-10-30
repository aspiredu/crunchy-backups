from datetime import date

from src.schedule import is_valid_saturday


def test_is_valid_saturday():
    assert not is_valid_saturday(date(2021, 1, 1))
    assert is_valid_saturday(date(2021, 1, 2))
    assert not is_valid_saturday(date(2021, 1, 3))
    assert not is_valid_saturday(date(2021, 1, 9))
    assert not is_valid_saturday(date(2021, 1, 15))
    assert is_valid_saturday(date(2021, 1, 16))
    assert not is_valid_saturday(date(2021, 1, 17))
