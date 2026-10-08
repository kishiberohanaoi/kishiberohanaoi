# studybot

タスク（課題・締切）の管理と、授業の対策資料づくりを Claude で自動化する CLI。

- `tasks.yaml` に授業と課題を書く → **今日/今週の学習計画**を自動生成
- `materials/<授業>/` に講義スライド(PDF)・ノート(.md/.txt)・板書写真を置く → **試験対策ノート / 想定問題 / チートシート**を自動生成
- `.ics`（UTOL やカレンダーの書き出し）から**締切を取り込み**
- GitHub Actions で**毎朝の計画を自動生成**

## セットアップ

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...   # https://console.anthropic.com で発行
```

## 使い方

### タスク管理

```bash
studybot list                                         # 未完了タスクを締切順に表示（AI不使用・無料）
studybot add "線形代数 レポート4" -c linalg -d 2026-10-22 -e 3
studybot done 4
studybot plan                                         # → output/plans/2026-10-08.md
studybot plan -r "土曜はバイトで使えない"
```

`tasks.yaml` は直接編集してもOK。授業の `exam`（試験日）や `schedule`（時間割）を書いておくと計画に反映されます。

### 対策資料の生成

```bash
# materials/linalg/ の資料を全部使って対策ノート
studybot study linalg
# ファイルを指定して想定問題
studybot study linalg materials/linalg/05_固有値.pdf materials/linalg/my_notes.md -k quiz
# チートシート、範囲を指定
studybot study linalg -k cheatsheet -f "第5〜8回、期末試験範囲"
```

出力先: `output/study/<授業ID>/<日付>-<種類>.md`

| `-k` | 内容 |
|---|---|
| `guide`（デフォルト） | 要約・重要概念・公式・ひっかけ・練習問題つき対策ノート |
| `quiz` | 一問一答・記述・発展問題と解答解説 |
| `cheatsheet` | A4 1枚に収まる要点まとめ |

1回で送れる資料は合計約 22MB まで。超える場合は回ごとに分けて実行してください。

### UTOL・カレンダーから締切を取り込む

```bash
studybot import-ics ~/Downloads/calendar.ics -c linalg
studybot import-ics "https://.../calendar.ics" -k "線形代数" -c linalg
```

UID で重複を防ぐので、同じ URL を何度取り込んでも大丈夫です。

> **UTOL からの自動取得について**: UTOL は UTokyo Account（多要素認証あり）でログインするため、
> ログインを自動化してスクレイピングするのは壊れやすく、規約面の確認も必要です。
> まずは UTOL やカレンダーアプリの **.ics 書き出し / 購読 URL** を使う方法にしています。
> 講義資料は UTOL からダウンロードして `materials/` に置いてください。

### 毎朝の自動計画（GitHub Actions）

リポジトリの Settings → Secrets and variables → Actions に `ANTHROPIC_API_KEY` を登録すると、
`.github/workflows/daily-plan.yml` が毎朝 7:00 (JST) に `output/plans/` へ計画をコミットします。
未登録の間は何もせずスキップします。

## 注意

- 講義資料（PDF・画像）は著作物のことが多いので、`.gitignore` で Git に上がらないようにしています。
  このリポジトリが公開なら、生成した対策資料のコミットにも気をつけてください。
- モデルはデフォルトで `claude-opus-5-5`。`STUDYBOT_MODEL` 環境変数で変更できます。
