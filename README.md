# MyHealth — 美容・健康のための運動管理アプリ

ブラウザで使う、美容と健康のための運動記録アプリです。運動を記録するだけでなく、美容・健康に関する情報を自動で集めて一覧で表示します。

## すぐに使う(ホスト版)

インストールなしでブラウザから使える版を claude.ai の Artifact として公開しています(持ち主だけが開ける非公開ページ)。

- ページ: https://claude.ai/artifact/CJb8WkWzZAVPagvEPtfSCX
- ソース: [`artifact/myhealth.html`](artifact/myhealth.html)
- データは Artifact のデータベースに保存され、PC とスマホのどちらから開いても同じ記録が見られます
- 情報収集は毎朝 6:51(日本時間)に Claude のルーティンが実行し、「収集キーワード」タブのキーワードでウェブ検索して記事を追加します。ルーティンの指示文は [`artifact/collector_prompt.md`](artifact/collector_prompt.md)

以下は自分の PC やサーバーで動かす Python 版の説明です。

## 主な機能

- **ダッシュボード**: 今週の運動時間と週の目標(初期値 150 分)、連続記録日数、目的別の内訳、直近 14 日間のグラフ、新着の情報
- **運動記録**: 日付・目的(美容 / 健康 / 美容・健康)・運動内容・時間・強度・消費 kcal・メモを登録、編集、削除。月ごと・目的ごとに表示
- **情報の自動収集**: 登録した情報源(RSS/Atom)から定期的に記事を取得(初期値は 6 時間ごと)。キーワード検索、カテゴリ・情報源での絞り込み、未読 / お気に入りの管理
- **情報源の管理**: キーワードを入力すると Google ニュース検索の RSS として登録されます。ブログやメディアの RSS URL を直接登録することもできます。初回起動時には「美容 運動」「健康 運動」などの情報源があらかじめ登録されています

## 起動方法

Python 3.10 以上が必要です。

```bash
python -m venv .venv
source .venv/bin/activate        # Windows の場合は .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

ブラウザで http://localhost:8000 を開きます。起動から数秒後に最初の情報収集が始まります。

スマートフォンなど同じネットワーク内の別の端末から見るときは `--host 0.0.0.0` を付けて起動し、`http://<PCのIPアドレス>:8000` を開いてください。

## 設定(環境変数)

| 変数 | 既定値 | 内容 |
| --- | --- | --- |
| `MYHEALTH_DB` | `data/myhealth.db` | SQLite データベースのパス |
| `MYHEALTH_COLLECT_INTERVAL_HOURS` | `6` | 自動収集の間隔(時間) |
| `MYHEALTH_DISABLE_SCHEDULER` | なし | `1` にすると自動収集を止める(「今すぐ収集」ボタンは使えます) |

## テスト

```bash
pip install -r requirements-dev.txt
pytest
```

## 構成

```
app/
  main.py        画面とルーティング(FastAPI)
  db.py          SQLite のスキーマと初期データ
  collector.py   RSS/Atom フィードの収集
  templates/     画面の HTML(Jinja2)
  static/        CSS
tests/           テスト
```
