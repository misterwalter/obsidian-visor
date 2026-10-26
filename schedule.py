#!/usr/bin/env python3
"""When a repeating job runs: its `Repeat:` line, read here for every kind of job that repeats (a
note in scheduled/ or idle/, a game, a character's board time), so that a word means the same
wherever it is written.

    Repeat: no                          not again
    Repeat: idle                        whenever there is nothing else to do
    Repeat: daily                       every day, at midnight
    Repeat: monday, wednesday, friday   those days, at midnight
    Repeat: weekdays, 07:00             Monday to Friday, at seven in the morning
    Repeat: 1, 15, last                 those days of the month (last and penultimate: its last two)
    Repeat: hourly, weekends            every hour, on Saturdays and Sundays
    Repeat: 08:00, 20:00                every day, twice

Days say which days, and add up: `monday, 1` is every Monday and the first of every month. Times
say when on those days: midnight when none is given, every hour with `hourly`. Commas or spaces
part the words. `idle` goes alone.

A scheduled job is due once a moment it is scheduled for has passed since its last run: so one that
could not run then, the queue being long or the server off, runs late, and once, however many
moments it missed. A daily job joins the queue at midnight. Times are the server's own clock.
"""

import calendar
import collections
import datetime
import re

IDLE, SCHEDULED = "idle", "scheduled"
NEVER = ("no", "none", "off", "")
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
GROUPS = {"weekdays": range(5), "weekends": (5, 6)}
ENDS = {"last": 1, "penultimate": 2}  # days of the month counted from its end
HELP = ("`daily`, `hourly`, days (`monday`, `weekdays`, `weekends`), days of the month (`1`, `15`, `last`, "
        "`penultimate`) and times (`07:00`), separated by commas; or `idle` alone, or `no`")
# How far back and on a schedule's moments are looked for: past the longest gap between two of them,
# a 31st that falls only in some months, run on the last day of the others.
SPAN = 62


class Schedule(collections.namedtuple("Schedule", "weekdays monthdays ends times")):
    """weekdays: {0..6}, Monday first; monthdays: {1..31}; ends: {1, 2}, days from the month's end;
    times: ((hour, minute), ...) in order. No days at all means every day."""

    def runs_on(self, day):
        if not (self.weekdays or self.monthdays or self.ends):
            return True
        last = calendar.monthrange(day.year, day.month)[1]
        # A day of the month past the end of a short one falls on its last day.
        return (day.weekday() in self.weekdays or day.day in self.monthdays
                or (day.day == last and any(n > last for n in self.monthdays))
                or (last - day.day + 1) in self.ends)


def read(text):
    """What a `Repeat:` line says: (how, schedule, problem). how is None (no repeat), IDLE or SCHEDULED;
    schedule is a Schedule for SCHEDULED, else None; problem says what visor could not read, and then
    how is None."""
    words = [w for w in re.split(r"[\s,]+", (text or "").strip().lower()) if w]
    if not words or (len(words) == 1 and words[0] in NEVER):
        return None, None, None
    if IDLE in words:
        if len(words) > 1:
            return None, None, ("`idle` means whenever there is nothing else to do, and goes with nothing else: "
                                f"`Repeat: idle`, or a schedule without it ({HELP}).")
        return IDLE, None, None
    weekdays, monthdays, ends, times, hourly = set(), set(), set(), set(), False
    for word in words:
        day, at = _day(word), _time(word)
        if word == "daily":
            continue
        elif word == "hourly":
            hourly = True
        elif word in GROUPS:
            weekdays.update(GROUPS[word])
        elif word in ENDS:
            ends.add(ENDS[word])
        elif day is not None:
            weekdays.add(day)
        elif word.isdigit() and 1 <= int(word) <= 31:
            monthdays.add(int(word))
        elif at:
            times.add(at)
        else:
            return None, None, f"`{word}` is not a day, a time or a word visor knows on `Repeat:`, which takes {HELP}."
    if hourly:
        times.update((hour, 0) for hour in range(24))
    if "daily" in words:
        weekdays, monthdays, ends = set(), set(), set()  # every day: no day left out
    return SCHEDULED, Schedule(frozenset(weekdays), frozenset(monthdays), frozenset(ends),
                               tuple(sorted(times or {(0, 0)}))), None


def _day(word):
    """A day of the week, Monday 0: `monday`, `mondays`, or the first three letters or more, `mon`, `thurs`."""
    stem = word[:-1] if word.endswith("s") and word[:-1] in DAYS else word
    return next((i for i, name in enumerate(DAYS) if stem == name or (len(stem) >= 3 and name.startswith(stem))),
                None)


def _time(word):
    """A time of day, as (hour, minute): `07:00`, `7:30`, `19:00`, `7am`, `7:30pm`; None for anything else."""
    found = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", word)
    if not found or (found.group(2) is None and found.group(3) is None):
        return None
    hour, minute, half = int(found.group(1)), int(found.group(2) or 0), found.group(3)
    if half:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if half == "pm" else 0)
    return (hour, minute) if hour < 24 and minute < 60 else None


def latest(schedule, now):
    """The last moment the schedule names at or before now, or None within SPAN days."""
    for back in range(SPAN):
        day = now.date() - datetime.timedelta(days=back)
        if schedule.runs_on(day):
            moments = [datetime.datetime.combine(day, datetime.time(h, m)) for h, m in schedule.times]
            passed = [m for m in moments if m <= now]
            if passed:
                return passed[-1]
    return None


def following(schedule, now):
    """The next moment the schedule names after now, or None within SPAN days."""
    for ahead in range(SPAN):
        day = now.date() + datetime.timedelta(days=ahead)
        if schedule.runs_on(day):
            for h, m in schedule.times:
                moment = datetime.datetime.combine(day, datetime.time(h, m))
                if moment > now:
                    return moment
    return None


def due(schedule, last, now):
    """Whether a job on this schedule should run: a moment it names has passed since it last ran
    (last: datetime, or None for never), or it has never run."""
    if last is None:
        return True
    moment = latest(schedule, now)
    return moment is not None and last < moment


def stamp(text):
    """A run's time as visor writes it, `2026-10-24 07:03` or with seconds, as a datetime; None if none."""
    for form in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime((text or "").strip(), form)
        except ValueError:
            continue
    return None


def said(moment, now):
    """A moment as STATUS.md says it: `today 07:00`, `tomorrow 00:00`, `Fri 07:00`, `Nov 1 00:00`."""
    days = (moment.date() - now.date()).days
    when = ("today" if days == 0 else "tomorrow" if days == 1 else moment.strftime("%a") if 1 < days < 7
            else f"{moment.strftime('%b')} {moment.day}")
    return f"{when} {moment.strftime('%H:%M')}"
