"""서버는 UTC다. 운영진의 하루·요일은 KST로 판단한다."""
from datetime import timedelta, timezone as dt_timezone

KST = dt_timezone(timedelta(hours=9), 'KST')
QUIET_FROM, QUIET_UNTIL = 21, 8


def kst_now(now):
    return now.astimezone(KST)


def kst_today(now):
    return kst_now(now).date()


def in_quiet_hours(now):
    hour = kst_now(now).hour
    return hour >= QUIET_FROM or hour < QUIET_UNTIL


def week_start(day):
    return day - timedelta(days=day.weekday())
