"""iCalendar (.ics) から課題・締切を取り込む。

UTOL などの LMS やカレンダーアプリが出せる .ics ファイル / 購読URL を想定。
"""

from __future__ import annotations

import datetime as dt
import urllib.request
from pathlib import Path

from icalendar import Calendar

from . import tasks


def read_source(source: str) -> bytes:
    if source.startswith(("http://", "https://", "webcal://")):
        url = source.replace("webcal://", "https://", 1)
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()
    return Path(source).read_bytes()


def _to_naive_local(value) -> dt.datetime | dt.date:
    if isinstance(value, dt.datetime) and value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def import_ics(data: dict, raw: bytes, course: str | None = None, keyword: str | None = None) -> list[dict]:
    """VTODO と VEVENT をタスクとして追加し、追加したタスクを返す。UID で重複を防ぐ。"""
    known_uids = {t.get("uid") for t in data["tasks"] if t.get("uid")}
    now = dt.datetime.now()
    added = []

    for comp in Calendar.from_ical(raw).walk():
        if comp.name not in ("VTODO", "VEVENT"):
            continue
        summary = str(comp.get("SUMMARY", "")).strip()
        if not summary or (keyword and keyword not in summary):
            continue
        uid = str(comp.get("UID", "")) or None
        if uid and uid in known_uids:
            continue

        prop = comp.get("DUE") or comp.get("DTEND") or comp.get("DTSTART")
        due = tasks.parse_due(_to_naive_local(prop.dt)) if prop else None
        if due and due < now:
            continue  # 過去の予定は取り込まない

        task = {
            "id": tasks.next_id(data),
            "title": summary,
            "course": course,
            "due": due.strftime("%Y-%m-%d %H:%M") if due else None,
            "status": "todo",
        }
        description = str(comp.get("DESCRIPTION", "")).strip()
        if description:
            task["notes"] = description[:500]
        if uid:
            task["uid"] = uid
            known_uids.add(uid)
        data["tasks"].append(task)
        added.append(task)
    return added
