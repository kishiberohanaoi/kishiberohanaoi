"""studybot のコマンドライン入口。"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import tasks

DEFAULT_TASKS = Path("tasks.yaml")
DEFAULT_OUT = Path("output")
DEFAULT_MATERIALS = Path("materials")


def cmd_list(args) -> None:
    data = tasks.load(args.tasks)
    now = dt.datetime.now()
    open_tasks = tasks.open_tasks_sorted(data)
    if not open_tasks:
        print("未完了のタスクはありません 🎉")
        return
    for t in open_tasks:
        due = tasks.parse_due(t.get("due"))
        due_str = due.strftime("%m/%d %H:%M") if due else "--/-- --:--"
        course = tasks.course_name(data, t.get("course"))
        est = f" ({t['estimate_h']}h)" if t.get("estimate_h") else ""
        print(f"[{t.get('id')}] {due_str} {tasks.describe_remaining(due, now):>8}  "
              f"{t.get('title')}{est}  {('#' + course) if course else ''}")


def cmd_add(args) -> None:
    data = tasks.load(args.tasks)
    if args.due:
        tasks.parse_due(args.due)  # 形式チェック
    if args.course and not tasks.find_course(data, args.course):
        print(f"注意: 授業 '{args.course}' は courses に未登録です。", file=sys.stderr)
    task = {"id": tasks.next_id(data), "title": args.title, "course": args.course,
            "due": args.due, "estimate_h": args.estimate, "status": "todo"}
    data["tasks"].append({k: v for k, v in task.items() if v is not None})
    tasks.save(args.tasks, data)
    print(f"追加しました: [{task['id']}] {args.title}")


def cmd_done(args) -> None:
    data = tasks.load(args.tasks)
    for t in data["tasks"]:
        if t.get("id") == args.id:
            t["status"] = "done"
            tasks.save(args.tasks, data)
            print(f"完了にしました: [{args.id}] {t.get('title')}")
            return
    sys.exit(f"ID {args.id} のタスクが見つかりません。")


def cmd_import_ics(args) -> None:
    from . import ics_import

    data = tasks.load(args.tasks)
    added = ics_import.import_ics(data, ics_import.read_source(args.source), args.course, args.keyword)
    tasks.save(args.tasks, data)
    print(f"{len(added)} 件のタスクを追加しました。")
    for t in added:
        print(f"  [{t['id']}] {t['due'] or '締切なし'}  {t['title']}")


def cmd_plan(args) -> None:
    from . import planner

    data = tasks.load(args.tasks)
    now = dt.datetime.now()
    text = planner.generate_plan(data, now, args.request or "")
    out = args.out / "plans" / f"{now:%Y-%m-%d}.md"
    write_output(out, text)


def cmd_study(args) -> None:
    from . import study

    data = tasks.load(args.tasks)
    course = tasks.find_course(data, args.course)
    course_id = course.get("id", args.course) if course else args.course
    paths = [Path(p) for p in args.files] or [DEFAULT_MATERIALS / str(course_id)]
    files = study.collect_files(paths)
    print(f"{len(files)} 個の資料から生成します: {', '.join(f.name for f in files)}", file=sys.stderr)

    text = study.generate_material(files, args.kind, course, args.focus or "")
    title = course.get("name", course_id) if course else course_id
    header = f"# {title} {args.kind}（{dt.date.today():%Y-%m-%d} 生成）\n\n資料: {', '.join(f.name for f in files)}\n\n"
    out = args.out / "study" / str(course_id) / f"{dt.date.today():%Y-%m-%d}-{args.kind}.md"
    write_output(out, header + text)


def write_output(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"保存しました: {path}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="studybot", description="タスク管理と授業の対策資料を自動生成する")
    p.add_argument("--tasks", type=Path, default=DEFAULT_TASKS, help="タスクファイル (default: tasks.yaml)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="出力先ディレクトリ (default: output)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("list", help="未完了タスクを締切順に表示（AI不使用）")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("add", help="タスクを追加")
    s.add_argument("title")
    s.add_argument("--course", "-c", help="授業ID")
    s.add_argument("--due", "-d", help="締切 例: 2026-10-15 または '2026-10-15 23:59'")
    s.add_argument("--estimate", "-e", type=float, help="見積もり時間 (h)")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("done", help="タスクを完了にする")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_done)

    s = sub.add_parser("import-ics", help=".ics ファイル/URL から締切を取り込む")
    s.add_argument("source", help=".ics のパスまたは URL")
    s.add_argument("--course", "-c", help="取り込んだタスクに付ける授業ID")
    s.add_argument("--keyword", "-k", help="タイトルにこの文字列を含む予定だけ取り込む")
    s.set_defaults(func=cmd_import_ics)

    s = sub.add_parser("plan", help="今日/今週の学習計画を生成（Claude）")
    s.add_argument("--request", "-r", help="追加の要望 例: '土曜はバイトで使えない'")
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("study", help="講義資料から対策資料を生成（Claude）")
    s.add_argument("course", help="授業ID（tasks.yaml の courses）")
    s.add_argument("files", nargs="*", help="資料ファイル/ディレクトリ。省略時は materials/<授業ID>/")
    s.add_argument("--kind", "-k", choices=["guide", "quiz", "cheatsheet"], default="guide",
                   help="guide=対策ノート, quiz=想定問題, cheatsheet=チートシート")
    s.add_argument("--focus", "-f", help="重視してほしいこと 例: '第5〜8回、期末試験'")
    s.set_defaults(func=cmd_study)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    from .llm import GenerationError

    try:
        args.func(args)
    except (GenerationError, ValueError, FileNotFoundError) as e:
        sys.exit(f"エラー: {e}")


if __name__ == "__main__":
    main()
