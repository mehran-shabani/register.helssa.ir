from django.utils import timezone

_PERSIAN_DIGITS_TRANSLATION = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


_PERSIAN_ARABIC_DIGITS_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
)


def to_english_digits(value):
    """Convert Persian/Arabic digits in a value to English digits."""

    return str(value or "").translate(_PERSIAN_ARABIC_DIGITS_TRANSLATION)


def _jalali_to_gregorian(year, month, day):
    """Convert a Jalali (Solar Hijri) date to a Gregorian date."""

    year = int(year)
    month = int(month)
    day = int(day)
    if not 1 <= month <= 12:
        raise ValueError("Invalid Jalali month.")
    max_day = 31 if month <= 6 else 30
    if not 1 <= day <= max_day:
        raise ValueError("Invalid Jalali day.")

    jalali_year = year - 979 if year > 979 else year
    days = 365 * jalali_year + (jalali_year // 33) * 8 + ((jalali_year % 33) + 3) // 4

    if month < 7:
        days += (month - 1) * 31
    else:
        days += 186 + (month - 7) * 30
    days += day - 1 + 79

    gregorian_year = 1600 + 400 * (days // 146097)
    days %= 146097

    leap = True
    if days >= 36525:
        days -= 1
        gregorian_year += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
        else:
            leap = False

    gregorian_year += 4 * (days // 1461)
    days %= 1461

    if days >= 366:
        leap = False
        days -= 1
        gregorian_year += days // 365
        days %= 365

    gregorian_month_days = [
        31,
        29 if leap else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ]
    gregorian_month = 1
    for month_days in gregorian_month_days:
        if days < month_days:
            break
        days -= month_days
        gregorian_month += 1

    return gregorian_year, gregorian_month, days + 1


def _gregorian_to_jalali(year, month, day):
    """Convert a Gregorian date to a Jalali (Solar Hijri) date."""

    gregorian_month_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]

    if year > 1600:
        jalali_year = 979
        year -= 1600
    else:
        jalali_year = 0
        year -= 621

    if month > 2:
        gy2 = year + 1
    else:
        gy2 = year

    days = (
        365 * year
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + day
        + gregorian_month_days[month - 1]
    )

    jalali_year += 33 * (days // 12053)
    days %= 12053
    jalali_year += 4 * (days // 1461)
    days %= 1461

    if days > 365:
        jalali_year += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jalali_month = 1 + days // 31
        jalali_day = 1 + days % 31
    else:
        jalali_month = 7 + (days - 186) // 30
        jalali_day = 1 + (days - 186) % 30

    return jalali_year, jalali_month, jalali_day


def to_persian_digits(value):
    return str(value).translate(_PERSIAN_DIGITS_TRANSLATION)


def _to_tehran_local(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return timezone.localtime(value)


def format_tehran_jalali_date(value):
    """Format an aware/naive date or datetime as a Jalali date in Tehran time."""

    if value is None:
        return "-"

    if hasattr(value, "hour"):
        value = _to_tehran_local(value)

    jalali_year, jalali_month, jalali_day = _gregorian_to_jalali(
        value.year, value.month, value.day
    )
    return to_persian_digits(f"{jalali_year:04d}/{jalali_month:02d}/{jalali_day:02d}")


def format_tehran_jalali(value):
    """Format an aware/naive datetime as Jalali date and Tehran local time."""

    local_value = _to_tehran_local(value)
    if local_value is None:
        return "-"

    return to_persian_digits(
        f"{format_tehran_jalali_date(local_value)} {local_value:%H:%M:%S}"
    )


def parse_tehran_jalali_datetime(value):
    """Parse a Jalali datetime string as an aware datetime in the project timezone."""

    import re
    from datetime import datetime

    normalized = to_english_digits(value).strip()
    match = re.fullmatch(
        r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?",
        normalized,
    )
    if not match:
        raise ValueError("Invalid Jalali datetime format.")

    jy, jm, jd, hour, minute, second = match.groups()
    hour = int(hour)
    minute = int(minute)
    second = int(second or 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59 or not 0 <= second <= 59:
        raise ValueError("Invalid Jalali datetime time.")

    gy, gm, gd = _jalali_to_gregorian(int(jy), int(jm), int(jd))
    naive_value = datetime(gy, gm, gd, hour, minute, second)
    return timezone.make_aware(naive_value, timezone.get_current_timezone())


def format_tehran_jalali_input(value):
    """Format a datetime for the Persian Jalali admin input."""

    local_value = _to_tehran_local(value)
    if local_value is None:
        return ""

    jalali_year, jalali_month, jalali_day = _gregorian_to_jalali(
        local_value.year, local_value.month, local_value.day
    )
    return to_persian_digits(
        f"{jalali_year:04d}/{jalali_month:02d}/{jalali_day:02d} {local_value:%H:%M}"
    )
