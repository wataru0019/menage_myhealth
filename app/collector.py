"""RSS/Atom フィードから美容・健康情報を収集する。"""

import calendar
import html
import logging
import re
from datetime import datetime

import feedparser
import httpx

from . import db

logger = logging.getLogger(__name__)

USER_AGENT = "menage-myhealth/1.0 (+https://github.com/wataru0019/menage_myhealth)"
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def clean_text(value: str, limit: int = 300) -> str:
    text = _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", value or ""))).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _published(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            # feedparser は UTC の struct_time を返すのでローカル時刻に直す
            return datetime.fromtimestamp(calendar.timegm(parsed)).strftime(
                "%Y-%m-%d %H:%M"
            )
    return None


def fetch_feed(url: str, timeout: float = 20.0) -> feedparser.FeedParserDict:
    resp = httpx.get(
        url, timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def collect_source(conn, source) -> int:
    """1 つの情報源を取得して新着記事数を返す。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        feed = fetch_feed(source["url"])
        if feed.bozo and not feed.entries:
            raise ValueError(f"フィードを解析できません: {feed.bozo_exception}")
    except Exception as exc:  # 1 件の失敗で全体を止めない
        logger.warning("collect failed: %s (%s)", source["url"], exc)
        conn.execute(
            "UPDATE sources SET last_fetched_at = ?, last_error = ? WHERE id = ?",
            (now, str(exc)[:500], source["id"]),
        )
        return 0

    added = 0
    for entry in feed.entries:
        link = entry.get("link")
        title = clean_text(entry.get("title", ""), limit=200)
        if not link or not title:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO articles (source_id, title, link, summary, published_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source["id"], title, link, clean_text(entry.get("summary", "")), _published(entry)),
        )
        added += cur.rowcount
    conn.execute(
        "UPDATE sources SET last_fetched_at = ?, last_error = NULL WHERE id = ?",
        (now, source["id"]),
    )
    return added


def collect_all(source_id: int | None = None) -> dict:
    """有効な情報源をすべて(または指定した 1 件を)収集する。"""
    with db.get_conn() as conn:
        if source_id is None:
            sources = conn.execute("SELECT * FROM sources WHERE enabled = 1").fetchall()
        else:
            sources = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchall()
        added = 0
        errors = 0
        for source in sources:
            added += collect_source(conn, source)
            conn.commit()
            if conn.execute(
                "SELECT last_error FROM sources WHERE id = ?", (source["id"],)
            ).fetchone()["last_error"]:
                errors += 1
    logger.info("collected %d new articles from %d sources", added, len(sources))
    return {"sources": len(sources), "added": added, "errors": errors}
