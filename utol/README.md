# UTOL 同期スクリプト

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

## 注意

- UTOL の画面構成を知らずに作っているので、最初は取りこぼしがあるかもしれません。
  うまく取れないページがあれば、そのページの URL と見え方を教えてください。
- `utol_export.json` には UTOL の画面の内容がそのまま入ります。人に渡したり、公開リポジトリにコミットしたりしないでください
  （`.gitignore` で除外しています）。
- 大学の利用規約の範囲で、自分のアカウントの情報を読むために使ってください。
