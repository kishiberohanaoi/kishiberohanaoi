"""講義スライド（PDF）・ノート（テキスト/Markdown）・板書写真から対策資料を生成する。"""

from __future__ import annotations

import base64
from pathlib import Path

from . import llm

PDF_EXTS = {".pdf"}
TEXT_EXTS = {".txt", ".md", ".markdown"}
IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
SUPPORTED_EXTS = PDF_EXTS | TEXT_EXTS | set(IMAGE_EXTS)

# API のリクエスト上限は 32MB。base64 で約 4/3 倍になるので元ファイル合計で余裕を持たせる。
MAX_TOTAL_BYTES = 22 * 1024 * 1024

KINDS = {
    "guide": """講義資料をもとに「試験対策ノート」を作ってください。構成:
1. 全体の要約（この範囲で何を学んだか、5〜10行）
2. 重要概念・用語（定義と、なぜ重要か）
3. 重要な公式・定理・手順（使いどころと注意点つき。数式は LaTeX）
4. よく出そうなポイント・ひっかけ
5. 練習問題（基本5問・応用3問程度。解答と解説は最後にまとめて「解答」セクションに）
6. 資料だけでは理解が不十分そうな箇所と、追加で調べるべきこと""",
    "quiz": """講義資料をもとに「想定問題集」を作ってください。
- 一問一答 10問、記述/計算問題 5問、発展問題 2問
- 難易度（★1〜3）と、資料のどこに対応するかを各問に付ける
- 解答と詳しい解説は最後の「解答・解説」セクションにまとめる""",
    "cheatsheet": """講義資料をもとに、A4 1枚に収まる「チートシート」を作ってください。
- 公式・定義・手順を最小限の言葉で、カテゴリ別に箇条書き
- 数式は LaTeX
- 説明文は極力省き、密度を優先""",
}

SYSTEM = """あなたは大学の授業の試験対策を手伝うチューターです。
渡された講義資料（スライド・ノート・板書写真など）の内容に基づいて、日本語の Markdown で資料を作ってください。
資料に書かれていない内容を補う場合は「（補足）」と明記し、資料由来の内容と区別してください。
どの資料のどこに基づくかがわかる場合は、(ファイル名 p.ページ) の形で示してください。"""


def collect_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS))
        elif p.is_file():
            if p.suffix.lower() not in SUPPORTED_EXTS:
                raise ValueError(f"未対応のファイル形式です: {p}（対応: {', '.join(sorted(SUPPORTED_EXTS))}）")
            files.append(p)
        else:
            raise FileNotFoundError(p)
    return files


def to_content_blocks(files: list[Path]) -> list[dict]:
    total = sum(f.stat().st_size for f in files)
    if total > MAX_TOTAL_BYTES:
        raise ValueError(
            f"資料の合計が {total / 1024 / 1024:.1f}MB あり、1回で送れる上限を超えています。"
            "回ごと・章ごとなどに分けて実行してください。"
        )

    blocks: list[dict] = []
    for f in files:
        ext = f.suffix.lower()
        if ext in PDF_EXTS:
            blocks.append({
                "type": "document",
                "title": f.name,
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(f.read_bytes()).decode(),
                },
            })
        elif ext in TEXT_EXTS:
            blocks.append({
                "type": "document",
                "title": f.name,
                "source": {"type": "text", "media_type": "text/plain", "data": f.read_text(encoding="utf-8")},
            })
        else:
            blocks.append({"type": "text", "text": f"次の画像: {f.name}"})
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": IMAGE_EXTS[ext],
                    "data": base64.standard_b64encode(f.read_bytes()).decode(),
                },
            })
    return blocks


def generate_material(files: list[Path], kind: str, course: dict | None, focus: str = "") -> str:
    if not files:
        raise ValueError("資料ファイルが見つかりません。materials/<授業ID>/ に PDF やノートを置いてください。")

    instructions = KINDS[kind]
    if course:
        info = ", ".join(f"{k}: {v}" for k, v in course.items())
        instructions = f"授業情報: {info}\n\n{instructions}"
    if focus:
        instructions += f"\n\n特に重視してほしいこと: {focus}"

    content = to_content_blocks(files) + [{"type": "text", "text": instructions}]
    return llm.generate(SYSTEM, content, effort="high")
