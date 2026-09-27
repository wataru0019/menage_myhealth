"""SQLite によるデータ保存。"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "myhealth.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    category TEXT NOT NULL,
    exercise TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    intensity TEXT NOT NULL DEFAULT '普通',
    calories INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(date);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_fetched_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    link TEXT NOT NULL UNIQUE,
    summary TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    is_read INTEGER NOT NULL DEFAULT 0,
    is_favorite INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CATEGORIES = ["美容", "健康", "美容・健康"]
INTENSITIES = ["軽め", "普通", "きつめ"]
DEFAULT_WEEKLY_GOAL_MIN = 150  # WHO 推奨の中強度運動量


def google_news_url(keyword: str) -> str:
    """キーワードから Google ニュース検索の RSS URL を作る。"""
    return f"https://news.google.com/rss/search?q={quote(keyword)}&hl=ja&gl=JP&ceid=JP:ja"


DEFAULT_SOURCES = [
    ("Googleニュース: 美容 運動", google_news_url("美容 運動"), "美容"),
    ("Googleニュース: 美肌 習慣", google_news_url("美肌 習慣"), "美容"),
    ("Googleニュース: 健康 運動", google_news_url("健康 運動"), "健康"),
    ("Googleニュース: 筋トレ 効果", google_news_url("筋トレ 効果"), "健康"),
    ("Googleニュース: ストレッチ 姿勢", google_news_url("ストレッチ 姿勢"), "美容・健康"),
]


def db_path() -> Path:
    return Path(os.environ.get("MYHEALTH_DB", DEFAULT_DB_PATH))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(seed_sources: bool = True) -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        if seed_sources and not conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone():
            conn.executemany(
                "INSERT INTO sources (name, url, category) VALUES (?, ?, ?)", DEFAULT_SOURCES
            )


def get_setting(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
