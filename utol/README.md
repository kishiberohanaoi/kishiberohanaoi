# UTOL 同期スクリプト

> スマホだけで取り込みたいときは、このスクリプトは不要です。アプリの「課題」タブ →「UTOL から取り込む」で、UTOL のページの文字を貼り付けるかスクリーンショットを選んでください。

UTOL の課題・お知らせ・講義資料を PC で集めて、学習デスク（アプリ）に取り込むためのスクリプトです。

## しくみ

1. スクリプトを実行すると、ブラウザが開きます。**ログインは自分で**行います（UTokyo Account の多要素認証もいつも通り）。
2. ログイン状態は `~/.studybot/utol-profile` に保存されるので、次回からは期限が切れるまでログイン不要です。
3. スクリプトが UTOL のページを**読むだけ**で巡回し、`utol_export.json` に書き出します。
   ログアウト・削除・提出・設定などのリンクはたどりません。ページ間は 1.5 秒あけます。
4. アプリの「課題」タブ →「UTOL から取り込む」でそのファイルを選ぶと、Claude が課題・締切・授業を抜き出します。
   追加する前に一覧で確認・選択できます。

パスワードはスクリプトに保存しません。

## 使い方

```bash
pip install playwright
playwright install chromium          # 初回だけ

python utol/utol_sync.py                        # 課題・お知らせを書き出す
python utol/utol_sync.py --download materials   # 講義資料(PDF等)も materials/utol/ に保存
python utol/utol_sync.py --chrome               # PC の Google Chrome を使う
python utol/utol_sync.py --max-pages 100        # たくさん授業がある場合
python utol/utol_sync.py --reset-login          # 別アカウントでログインし直す
```

ダウンロードした講義資料は、アプリの「対策資料」タブでそのまま選べます。

## 毎朝自動で同期する

一度ふつうに実行してログインしておいてから、自動実行を登録します。

```bash
python utol/utol_sync.py --install-schedule 07:00 \
    --out "~/Library/Mobile Documents/com~apple~CloudDocs/utol_export.json" \
    --ntfy 好きなトピック名
```

- 毎日指定した時刻に、画面を出さずに UTOL を読み込んで `--out` に書き出します。
  iCloud Drive / Google Drive / OneDrive のフォルダに書き出すと、スマホのアプリからそのファイルを選べます。
  （例: Windows の OneDrive なら `--out "%USERPROFILE%\OneDrive\utol_export.json"`）
- **ログインが切れていたら通知します。** そのときは PC で `python utol/utol_sync.py` を実行してログインし直してください。
  - PC: macOS / Windows / Linux のデスクトップ通知
  - スマホ: [ntfy](https://ntfy.sh/) アプリ（無料・アカウント不要）を入れて、`--ntfy` に指定したトピック名を購読すると届きます。
    トピック名は誰でも購読できるので、`utol-` のあとにランダムな文字を付けるなど、推測されにくい名前にしてください。
  - 通知のテスト: `python utol/utol_sync.py --test-notify --ntfy トピック名`
- 成功したときも通知がほしい場合は `--notify-success` を付けます。
- `--download materials` を付けると講義資料も毎朝ダウンロードします。
- 解除: `python utol/utol_sync.py --uninstall-schedule`
- ログ: `~/.studybot/utol-sync.log`

登録のしくみ: Windows はタスクスケジューラ、macOS は launchd、Linux は cron に登録します。
PC の電源が入っていて、スリープしていないときに動きます（macOS はスリープから復帰したときに実行されます）。

ログイン状態がどれくらい持つかは大学側の設定次第で、試すまでわかりません。数日おきにログインし直しになる可能性もあります。

## 注意

- UTOL の画面構成を知らずに作っているので、最初は取りこぼしがあるかもしれません。
  うまく取れないページがあれば、そのページの URL と見え方を教えてください。
- `utol_export.json` には UTOL の画面の内容がそのまま入ります。人に渡したり、公開リポジトリにコミットしたりしないでください
  （`.gitignore` で除外しています）。
- 大学の利用規約の範囲で、自分のアカウントの情報を読むために使ってください。
