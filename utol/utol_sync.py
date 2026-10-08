"""UTOL のページを巡回して、課題・お知らせ・教材の情報を utol_export.json に書き出す。

- ログインは開いたブラウザで自分で行う（UTokyo Account の多要素認証もそのまま）。
  ログイン状態は ~/.studybot/utol-profile に保存されるので、次回からは期限が切れるまで不要。
- ページは「読むだけ」。ログアウト・削除・提出などのリンクはたどらない。
- 書き出したファイルを学習デスク（アプリ）の「UTOL から取り込む」で読み込む。

使い方:
    pip install playwright
    playwright install chromium
    python utol/utol_sync.py                       # 課題・お知らせを書き出す
    python utol/utol_sync.py --download materials  # 講義資料(PDF等)もダウンロード
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urldefrag, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

DEFAULT_URL = "https://utol.ecc.u-tokyo.ac.jp/"
PROFILE_DIR = Path.home() / ".studybot" / "utol-profile"

# たどらないリンク（状態を変える可能性があるもの）
SKIP = re.compile(
    r"logout|log-out|signout|ログアウト|delete|remove|削除|submit|提出する|送信|unsubscribe|"
    r"setting|設定|password|パスワード|javascript:",
    re.I,
)
# 優先してたどるリンク
PRIORITY = re.compile(
    r"課題|レポート|report|assignment|テスト|test|quiz|試験|お知らせ|notice|news|"
    r"course|授業|コース|教材|資料|material|syllabus|シラバス",
    re.I,
)
FILE_EXT = re.compile(r"\.(pdf|pptx?|docx?|xlsx?|zip)(?:[?#]|$)", re.I)
MAX_TEXT_PER_PAGE = 15000
MAX_FILE_BYTES = 50 * 1024 * 1024


def main() -> None:
    p = argparse.ArgumentParser(description="UTOL の課題・お知らせ・教材を書き出す")
    p.add_argument("--url", default=DEFAULT_URL, help=f"開始URL (default: {DEFAULT_URL})")
    p.add_argument("--max-pages", type=int, default=60, help="巡回する最大ページ数 (default: 60)")
    p.add_argument("--delay", type=float, default=1.5, help="ページ間の待ち時間・秒 (default: 1.5)")
    p.add_argument("--out", type=Path, default=Path("utol_export.json"), help="出力ファイル")
    p.add_argument("--download", type=Path, help="講義資料をこのフォルダにダウンロードする")
    p.add_argument("--chrome", action="store_true", help="Playwright の Chromium ではなく、PC に入っている Google Chrome を使う")
    p.add_argument("--executable", help="使うブラウザの実行ファイルのパス")
    p.add_argument("--reset-login", action="store_true", help="保存したログイン状態を使わない")
    args = p.parse_args()

    if args.reset_login and PROFILE_DIR.exists():
        import shutil
        shutil.rmtree(PROFILE_DIR)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    host = urlparse(args.url).hostname

    with sync_playwright() as pw:
        launch = {"headless": False, "accept_downloads": True}
        if args.chrome:
            launch["channel"] = "chrome"
        if args.executable:
            launch["executable_path"] = args.executable
        ctx = pw.chromium.launch_persistent_context(str(PROFILE_DIR), **launch)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(args.url)

        print("\n開いたブラウザで UTOL にログインしてください（すでにログイン済みならそのままでOK）。")
        print("UTOL のトップページ（授業一覧が見える画面）が表示されたら、ここで Enter を押してください。")
        input("> ")
        if urlparse(page.url).hostname != host:
            print(f"まだ UTOL の画面ではないようです（今のURL: {page.url}）。ログインを完了してから再実行してください。")
            ctx.close()
            sys.exit(1)

        pages, files = crawl(page, page.url, host, args.max_pages, args.delay)
        if args.download:
            download_files(ctx, files, args.download, args.delay)
        ctx.close()

    export = {
        "source": "utol",
        "exportedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "pages": pages,
        "files": files,
    }
    args.out.write_text(json.dumps(export, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(pages)} ページ・{len(files)} 個の資料リンクを {args.out} に書き出しました。")
    print("学習デスクの「課題」タブ →「UTOL から取り込む」でこのファイルを選んでください。")


def crawl(page, start: str, host: str, max_pages: int, delay: float):
    high, low = deque([start]), deque()
    seen = {start}
    pages, files, texts = [], {}, set()

    while (high or low) and len(pages) < max_pages:
        url = high.popleft() if high else low.popleft()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(int(delay * 1000))
        except PlaywrightError as e:
            print(f"  スキップ（読み込み失敗）: {url} ({e.message.splitlines()[0]})")
            continue
        if urlparse(page.url).hostname != host:
            print("UTOL の外に移動しました。ログインが切れた可能性があるので、ここで巡回を止めます。")
            break

        title = page.title()
        try:
            text = page.inner_text("body")
        except PlaywrightError:
            text = ""
        text = re.sub(r"\n{3,}", "\n\n", text).strip()[:MAX_TEXT_PER_PAGE]
        if text and text not in texts:
            texts.add(text)
            pages.append({"url": page.url, "title": title, "text": text})
            print(f"  [{len(pages)}/{max_pages}] {title or page.url}")

        links = page.eval_on_selector_all(
            "a[href]", "els => els.map(e => ({href: e.href, text: (e.innerText || e.title || '').trim()}))"
        )
        for link in links:
            href, _ = urldefrag(link["href"])
            label = link["text"]
            parsed = urlparse(href)
            if parsed.scheme not in ("http", "https") or parsed.hostname != host:
                continue
            if SKIP.search(href) or SKIP.search(label):
                continue
            if FILE_EXT.search(href) or re.search(r"download|ダウンロード", href + label, re.I):
                files.setdefault(href, {"url": href, "label": label, "foundOn": title})
                continue
            if href in seen:
                continue
            seen.add(href)
            (high if PRIORITY.search(label) or PRIORITY.search(href) else low).append(href)

    return pages, list(files.values())


def download_files(ctx, files: list[dict], root: Path, delay: float) -> None:
    print(f"\n講義資料を {root} にダウンロードします…")
    for f in files:
        try:
            resp = ctx.request.get(f["url"], timeout=60000)
        except PlaywrightError as e:
            print(f"  失敗: {f['label'] or f['url']} ({e.message.splitlines()[0]})")
            continue
        body = resp.body() if resp.ok else b""
        if not body or len(body) > MAX_FILE_BYTES or "text/html" in resp.headers.get("content-type", ""):
            continue  # ページだった・大きすぎる・取得失敗
        name = filename_from(resp.headers.get("content-disposition", ""), f["url"], f["label"])
        folder = root / "utol" / safe(f["foundOn"] or "その他")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(body)
        f["savedAs"] = str(path)
        print(f"  保存: {path}")
        time.sleep(delay)


def filename_from(disposition: str, url: str, label: str) -> str:
    m = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I) or re.search(r'filename="?([^";]+)', disposition, re.I)
    if m:
        return safe(unquote(m.group(1)))
    tail = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    return safe(tail or label or "file")


def safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\n\r\t]', "_", name).strip()[:120] or "file"


if __name__ == "__main__":
    main()
