"""UTOL のページを巡回して、課題・お知らせ・教材の情報を utol_export.json に書き出す。

- ログインは開いたブラウザで自分で行う（UTokyo Account の多要素認証もそのまま）。
  ログイン状態は ~/.studybot/ に保存されるので、次回からはサーバー側で期限が切れるまで不要。
- ページは「読むだけ」。ログアウト・削除・提出などのリンクはたどらない。
- 書き出したファイルを学習デスク（アプリ）の「UTOL から取り込む」で読み込む。

使い方:
    pip install playwright
    playwright install chromium
    python utol/utol_sync.py                       # 課題・お知らせを書き出す
    python utol/utol_sync.py --download materials  # 講義資料(PDF等)もダウンロード
    python utol/utol_sync.py --install-schedule 07:00 --out ~/iCloudDrive/utol_export.json --ntfy 好きなトピック名
                                                   # 毎朝7時に自動実行。ログインが切れたら通知
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urldefrag, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

DEFAULT_URL = "https://utol.ecc.u-tokyo.ac.jp/"
STATE_DIR = Path.home() / ".studybot"
PROFILE_DIR = STATE_DIR / "utol-profile"
COOKIE_FILE = STATE_DIR / "utol-cookies.json"
LOG_FILE = STATE_DIR / "utol-sync.log"
TASK_NAME = "StudybotUTOL"

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
    p.add_argument("--reset-login", action="store_true", help="保存したログイン状態を消してログインし直す")
    p.add_argument("--auto", action="store_true",
                   help="画面を出さずに実行（自動実行用）。ログインが切れていたら通知して終了する")
    p.add_argument("--ntfy", metavar="TOPIC", help="スマホに通知を送る ntfy のトピック名（他人に推測されにくい名前に）")
    p.add_argument("--notify-success", action="store_true", help="自動実行が成功したときも通知する")
    p.add_argument("--install-schedule", metavar="HH:MM", help="毎日この時刻に --auto で実行するよう登録する")
    p.add_argument("--uninstall-schedule", action="store_true", help="自動実行の登録を解除する")
    p.add_argument("--test-notify", action="store_true", help="通知のテストだけする")
    args = p.parse_args()
    args.out = args.out.expanduser().resolve()
    if args.download:
        args.download = args.download.expanduser().resolve()

    if args.test_notify:
        notify(args, "学習デスク", "UTOL 同期の通知テストです。")
        return
    if args.uninstall_schedule:
        uninstall_schedule()
        return
    if args.install_schedule:
        install_schedule(args)
        return

    if args.reset_login:
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
        COOKIE_FILE.unlink(missing_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    if not args.auto:
        run(args)
        return
    try:
        result = run(args)
    except LoginExpired:
        notify(args, "UTOL のログインが切れました",
               "PC で python utol/utol_sync.py を実行して、ログインし直してください。")
        sys.exit(2)
    except Exception as e:  # 自動実行では、どんな失敗も通知で知らせる
        notify(args, "UTOL の同期に失敗しました", f"{type(e).__name__}: {e}"[:300])
        raise
    if result["pages"] < 2:
        notify(args, "UTOL の同期で取れたページがほとんどありません",
               "ログインが切れているかもしれません。PC で python utol/utol_sync.py を実行して確認してください。")
    elif args.notify_success:
        notify(args, "UTOL を同期しました", f"{result['pages']} ページ・資料 {result['files']} 件を書き出しました。")


class LoginExpired(Exception):
    pass


def run(args) -> dict:
    host = urlparse(args.url).hostname
    with sync_playwright() as pw:
        launch = {"headless": args.auto, "accept_downloads": True}
        if args.chrome:
            launch["channel"] = "chrome"
        if args.executable:
            launch["executable_path"] = args.executable
        ctx = pw.chromium.launch_persistent_context(str(PROFILE_DIR), **launch)
        try:
            load_cookies(ctx)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(args.url)

            if args.auto:
                page.wait_for_timeout(3000)
                if not looks_logged_in(page, host):
                    raise LoginExpired()
            else:
                print("\n開いたブラウザで UTOL にログインしてください（すでにログイン済みならそのままでOK）。")
                print("UTOL のトップページ（授業一覧が見える画面）が表示されたら、ここで Enter を押してください。")
                input("> ")
                if not looks_logged_in(page, host):
                    print(f"まだ UTOL にログインできていないようです（今のURL: {page.url}）。ログインを完了してから再実行してください。")
                    sys.exit(1)
            save_cookies(ctx)

            pages, files = crawl(page, page.url, host, args.max_pages, args.delay)
            if args.download:
                download_files(ctx, files, args.download, args.delay)
            save_cookies(ctx)
        finally:
            ctx.close()

    export = {
        "source": "utol",
        "exportedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "pages": pages,
        "files": files,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(export, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(pages)} ページ・{len(files)} 個の資料リンクを {args.out} に書き出しました。")
    print("学習デスクの「課題」タブ →「UTOL から取り込む」でこのファイルを選んでください。")
    return {"pages": len(pages), "files": len(files)}


def looks_logged_in(page, host: str) -> bool:
    """UTOL の画面にいて、パスワード入力欄がなければログイン済みとみなす。"""
    if urlparse(page.url).hostname != host:
        return False
    try:
        return page.locator("input[type=password]").count() == 0
    except PlaywrightError:
        return False


# ブラウザを閉じると消える「セッション Cookie」も含めて保存し、次回の起動時に戻す
def save_cookies(ctx) -> None:
    COOKIE_FILE.write_text(json.dumps(ctx.cookies(), ensure_ascii=False), encoding="utf-8")
    try:
        COOKIE_FILE.chmod(0o600)
    except OSError:
        pass


def load_cookies(ctx) -> None:
    if not COOKIE_FILE.exists():
        return
    try:
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        now = time.time()
        ctx.add_cookies([c for c in cookies if c.get("expires", -1) in (-1, None) or c["expires"] > now])
    except (ValueError, PlaywrightError):
        pass


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


# ---------- 通知 ----------

def notify(args, title: str, message: str) -> None:
    """PC のデスクトップ通知と、指定があれば ntfy でスマホにも通知する。失敗しても止まらない。"""
    print(f"[通知] {title}: {message}")
    system = platform.system()
    try:
        if system == "Darwin":
            script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
            subprocess.run(["osascript", "-e", script], check=False, timeout=10)
        elif system == "Windows":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; "
                f"$n.Visible = $true; $n.ShowBalloonTip(10000, '{_ps(title)}', '{_ps(message)}', 'Info'); "
                "Start-Sleep -Seconds 10; $n.Dispose()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False, timeout=30)
        else:
            subprocess.run(["notify-send", title, message], check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass

    if getattr(args, "ntfy", None):
        body = json.dumps({"topic": args.ntfy, "title": title, "message": message, "tags": ["books"]}).encode()
        req = urllib.request.Request("https://ntfy.sh/", data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=15).close()
        except OSError as e:
            print(f"ntfy への通知に失敗しました: {e}")


def _ps(text: str) -> str:
    return text.replace("'", "''")


# ---------- 自動実行の登録 ----------

def install_schedule(args) -> None:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", args.install_schedule)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        sys.exit("時刻は 07:00 のように HH:MM で指定してください。")
    hour, minute = int(m.group(1)), int(m.group(2))
    if not COOKIE_FILE.exists():
        print("注意: まだ一度もログインしていないようです。先に python utol/utol_sync.py を実行してログインしておいてください。")

    cmd = [sys.executable, str(Path(__file__).resolve()), "--auto", "--out", str(args.out),
           "--max-pages", str(args.max_pages), "--delay", str(args.delay), "--url", args.url]
    if args.download:
        cmd += ["--download", str(args.download)]
    if args.chrome:
        cmd.append("--chrome")
    if args.executable:
        cmd += ["--executable", args.executable]
    if args.ntfy:
        cmd += ["--ntfy", args.ntfy]
    if args.notify_success:
        cmd.append("--notify-success")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    system = platform.system()

    if system == "Windows":
        wrapper = STATE_DIR / "run_utol_sync.cmd"
        wrapper.write_text("@echo off\r\nchcp 65001 >nul\r\n" + subprocess.list2cmdline(cmd)
                           + f' >> "{LOG_FILE}" 2>&1\r\n', encoding="utf-8")
        subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/TN", TASK_NAME,
                        "/ST", f"{hour:02d}:{minute:02d}", "/TR", f'"{wrapper}"'], check=True)
    elif system == "Darwin":
        wrapper = STATE_DIR / "run_utol_sync.sh"
        wrapper.write_text("#!/bin/sh\n" + shlex.join(cmd) + f' >> {shlex.quote(str(LOG_FILE))} 2>&1\n', encoding="utf-8")
        wrapper.chmod(0o755)
        plist = Path.home() / "Library" / "LaunchAgents" / "com.studybot.utol.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.studybot.utol</string>
  <key>ProgramArguments</key><array><string>/bin/sh</string><string>{wrapper}</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>{minute}</integer></dict>
</dict></plist>
""", encoding="utf-8")
        subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)], check=True)
    else:
        if not shutil.which("crontab"):
            sys.exit("crontab が見つかりません。cron をインストールしてから再実行してください。")
        wrapper = STATE_DIR / "run_utol_sync.sh"
        wrapper.write_text("#!/bin/sh\n" + shlex.join(cmd) + f' >> {shlex.quote(str(LOG_FILE))} 2>&1\n', encoding="utf-8")
        wrapper.chmod(0o755)
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        lines = [l for l in current.splitlines() if "# studybot-utol" not in l]
        lines.append(f"{minute} {hour} * * * /bin/sh {shlex.quote(str(wrapper))} # studybot-utol")
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)

    print(f"毎日 {hour:02d}:{minute:02d} に UTOL を同期するよう登録しました。")
    print(f"  書き出し先: {args.out}")
    print(f"  ログ: {LOG_FILE}")
    print("PC の電源が入っていて、スリープしていないときに動きます。")
    if args.ntfy:
        print(f"スマホの ntfy アプリでトピック「{args.ntfy}」を購読すると、通知がスマホに届きます。")


def uninstall_schedule() -> None:
    system = platform.system()
    if system == "Windows":
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], check=False)
    elif system == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.studybot.utol.plist"
        subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
        plist.unlink(missing_ok=True)
    elif shutil.which("crontab"):
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        lines = [l for l in current.splitlines() if "# studybot-utol" not in l]
        subprocess.run(["crontab", "-"], input="\n".join(lines) + ("\n" if lines else ""), text=True, check=False)
    print("自動実行の登録を解除しました。")


if __name__ == "__main__":
    main()
