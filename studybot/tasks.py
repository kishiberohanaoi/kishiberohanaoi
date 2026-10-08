"""tasks.yaml の読み書きと締切計算。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

DONE_STATUSES = {"done", "完了"}


def load(path: Path) -> dict:
    if not path.exists():
        return {"courses": [], "tasks": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("courses", [])
    data.setdefault("tasks", [])
    return data


def save(path: Path, data: dict) -> None:
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def parse_due(value) -> dt.datetime | None:
    """'2026-10-15' / '2026-10-15 23:59' / date / datetime を datetime にする。日付のみなら 23:59 扱い。"""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time(23, 59))
    s = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
        return parsed.replace(hour=23, minute=59) if fmt == "%Y-%m-%d" else parsed
    raise ValueError(f"締切の形式が読めません: {value!r}（例: 2026-10-15 または 2026-10-15 23:59）")


def is_open(task: dict) -> bool:
    return str(task.get("status", "todo")).lower() not in DONE_STATUSES


def open_tasks_sorted(data: dict) -> list[dict]:
    far_future = dt.datetime.max
    return sorted(
        (t for t in data["tasks"] if is_open(t)),
        key=lambda t: parse_due(t.get("due")) or far_future,
    )


def next_id(data: dict) -> int:
    ids = [t["id"] for t in data["tasks"] if isinstance(t.get("id"), int)]
    return max(ids, default=0) + 1


def course_name(data: dict, course_id) -> str:
    for c in data["courses"]:
        if c.get("id") == course_id:
            return c.get("name", str(course_id))
    return str(course_id or "")


def find_course(data: dict, key: str) -> dict | None:
    for c in data["courses"]:
        if key in (c.get("id"), c.get("name")):
            return c
    return None


def describe_remaining(due: dt.datetime | None, now: dt.datetime) -> str:
    if due is None:
        return "締切なし"
    delta = due - now
    if delta.total_seconds() < 0:
        return "期限切れ"
    days = delta.days
    if days == 0:
        return f"あと{delta.seconds // 3600}時間"
    return f"あと{days}日"
