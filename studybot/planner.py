"""タスク一覧から学習計画を生成する。"""

from __future__ import annotations

import datetime as dt

import yaml

from . import llm, tasks

WEEKDAYS = "月火水木金土日"

SYSTEM = """あなたは大学生の学習・タスク管理を手伝うアシスタントです。
渡された授業一覧とタスク一覧をもとに、現実的に実行できる計画を日本語の Markdown で作ってください。

出力の構成:
1. 「今日やること」: 優先度順に3〜5個。各項目に目安時間と、なぜ今日やるべきかを一言。
2. 「今週の計画」: 今日から7日分、日ごとに何をどれくらいやるか。授業の時間割（schedule）がある日は負荷を軽めに。
3. 「要注意」: 期限切れ・締切が重なっている・見積もりに対して時間が足りないもの。
4. 「試験対策の進め方」: 試験日（exam）が近い授業があれば、逆算した準備スケジュール。

締切が近いもの、見積もり時間が大きいもの、試験に直結するものを優先してください。
estimate_h（見積もり時間）がないタスクは内容から推測し、推測であることを明記してください。"""


def build_prompt(data: dict, now: dt.datetime) -> str:
    open_tasks = []
    for t in tasks.open_tasks_sorted(data):
        due = tasks.parse_due(t.get("due"))
        item = {k: v for k, v in t.items() if k != "uid"}
        item["course"] = tasks.course_name(data, t.get("course"))
        item["due"] = due.strftime("%Y-%m-%d %H:%M") if due else None
        item["remaining"] = tasks.describe_remaining(due, now)
        open_tasks.append(item)

    payload = {"courses": data["courses"], "open_tasks": open_tasks}
    today = f"{now:%Y-%m-%d %H:%M}（{WEEKDAYS[now.weekday()]}曜日）"
    return (
        f"現在日時: {today}\n\n"
        "以下が授業と未完了タスクの一覧です。\n\n"
        f"```yaml\n{yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)}```"
    )


def generate_plan(data: dict, now: dt.datetime, extra_request: str = "") -> str:
    prompt = build_prompt(data, now)
    if extra_request:
        prompt += f"\n\n追加の要望: {extra_request}"
    body = llm.generate(SYSTEM, [{"type": "text", "text": prompt}], effort="medium", max_tokens=32000)
    return f"# 学習計画 {now:%Y-%m-%d}\n\n{body}\n"
