from datetime import date

import feedparser

from app import collector, db

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>test</title>
<item><title>朝ヨガで美肌に</title><link>https://example.com/a</link>
<description>&lt;b&gt;ヨガ&lt;/b&gt;の効果</description>
<pubDate>Sat, 26 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>スクワットの正しいやり方</title><link>https://example.com/b</link></item>
</channel></rss>"""


def fake_fetch(url, timeout=20.0):
    return feedparser.parse(SAMPLE_RSS.encode())


def test_default_sources_seeded(client):
    res = client.get("/sources")
    assert res.status_code == 200
    assert "Googleニュース: 美容 運動" in res.text


def test_activity_crud_and_dashboard(client):
    today = date.today().isoformat()
    res = client.post(
        "/activities",
        data={"activity_date": today, "category": "美容", "exercise": "ヨガ",
              "duration_min": "40", "intensity": "普通", "calories": "", "notes": "朝"},
    )
    assert res.status_code == 200
    assert "ヨガ" in res.text

    dash = client.get("/")
    assert "40<small> / 150 分" in dash.text
    assert "1<small> 日" in dash.text  # streak

    with db.get_conn() as conn:
        activity_id = conn.execute("SELECT id FROM activities").fetchone()["id"]
    client.post(
        f"/activities/{activity_id}",
        data={"activity_date": today, "category": "健康", "exercise": "ランニング",
              "duration_min": "20", "intensity": "きつめ", "calories": "200"},
    )
    listing = client.get("/activities").text
    assert "ランニング" in listing and "200 kcal" in listing

    client.post(f"/activities/{activity_id}/delete")
    assert "この月の記録はありません" in client.get("/activities").text


def test_invalid_activity_rejected(client):
    res = client.post(
        "/activities",
        data={"activity_date": "2026-01-01", "category": "不明", "exercise": "x",
              "duration_min": "10"},
    )
    assert res.status_code == 400


def test_goal_update(client):
    client.post("/settings/goal", data={"weekly_goal_min": "200"})
    assert "/ 200 分" in client.get("/").text


def test_collect_and_news_listing(client, monkeypatch):
    monkeypatch.setattr(collector, "fetch_feed", fake_fetch)
    res = client.post("/news/collect")
    assert res.status_code == 200
    with db.get_conn() as conn:
        # 同じ記事は重複登録されない
        assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 2
        article = conn.execute("SELECT * FROM articles WHERE link = 'https://example.com/a'").fetchone()
    assert article["summary"] == "ヨガ の効果"
    assert article["published_at"] is not None

    news = client.get("/news?q=ヨガ").text
    assert "朝ヨガで美肌に" in news and "スクワット" not in news

    client.post(f"/news/{article['id']}/favorite")
    assert "朝ヨガで美肌に" in client.get("/news?view=favorite").text

    res = client.get(f"/news/{article['id']}/open", follow_redirects=False)
    assert res.headers["location"] == "https://example.com/a"
    assert "朝ヨガで美肌に" not in client.get("/news?view=unread").text


def test_collect_error_is_recorded(client, monkeypatch):
    def boom(url, timeout=20.0):
        raise RuntimeError("network down")

    monkeypatch.setattr(collector, "fetch_feed", boom)
    result = collector.collect_all()
    assert result["errors"] == result["sources"] > 0
    assert "エラー" in client.get("/sources").text


def test_add_source_by_keyword(client, monkeypatch):
    monkeypatch.setattr(collector, "fetch_feed", fake_fetch)
    client.post("/sources", data={"keyword": "腸活", "category": "健康"})
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM sources WHERE name = 'Googleニュース: 腸活'").fetchone()
    assert row is not None
    assert row["url"] == db.google_news_url("腸活")
    assert row["last_fetched_at"] is not None
