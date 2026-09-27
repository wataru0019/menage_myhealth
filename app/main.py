"""美容・健康のための運動管理アプリ。"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import collector, db

logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals.update(categories=db.CATEGORIES, intensities=db.INTENSITIES)

PAGE_SIZE = 30


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scheduler = None
    if os.environ.get("MYHEALTH_DISABLE_SCHEDULER") != "1":
        hours = float(os.environ.get("MYHEALTH_COLLECT_INTERVAL_HOURS", "6"))
        scheduler = BackgroundScheduler()
        # 起動直後に 1 回、その後は一定間隔で自動収集する
        scheduler.add_job(
            collector.collect_all, "interval", hours=hours, next_run_time=_soon()
        )
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


def _soon():
    return datetime.now() + timedelta(seconds=5)


app = FastAPI(title="美容・健康 運動管理", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ---------------------------------------------------------------- ダッシュボード


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    since = today - timedelta(days=13)
    with db.get_conn() as conn:
        goal = int(db.get_setting(conn, "weekly_goal_min", str(db.DEFAULT_WEEKLY_GOAL_MIN)))
        week_total = conn.execute(
            "SELECT COALESCE(SUM(duration_min), 0) FROM activities WHERE date >= ?",
            (week_start.isoformat(),),
        ).fetchone()[0]
        by_category = conn.execute(
            "SELECT category, SUM(duration_min) AS minutes, COUNT(*) AS count "
            "FROM activities WHERE date >= ? GROUP BY category ORDER BY minutes DESC",
            (week_start.isoformat(),),
        ).fetchall()
        daily_rows = conn.execute(
            "SELECT date, SUM(duration_min) AS minutes FROM activities "
            "WHERE date >= ? GROUP BY date",
            (since.isoformat(),),
        ).fetchall()
        active_days = {
            r["date"] for r in conn.execute("SELECT DISTINCT date FROM activities").fetchall()
        }
        recent = conn.execute(
            "SELECT * FROM activities ORDER BY date DESC, id DESC LIMIT 5"
        ).fetchall()
        top_exercises = conn.execute(
            "SELECT exercise, COUNT(*) AS count, SUM(duration_min) AS minutes "
            "FROM activities WHERE date >= ? GROUP BY exercise ORDER BY minutes DESC LIMIT 5",
            ((today - timedelta(days=29)).isoformat(),),
        ).fetchall()
        news = conn.execute(
            "SELECT a.*, s.name AS source_name, s.category FROM articles a "
            "JOIN sources s ON s.id = a.source_id WHERE a.is_read = 0 "
            "ORDER BY COALESCE(a.published_at, a.fetched_at) DESC LIMIT 6"
        ).fetchall()
        unread = conn.execute("SELECT COUNT(*) FROM articles WHERE is_read = 0").fetchone()[0]

    minutes_by_day = {r["date"]: r["minutes"] for r in daily_rows}
    daily = [
        {
            "date": d,
            "label": f"{d.month}/{d.day}",
            "minutes": minutes_by_day.get(d.isoformat(), 0),
        }
        for d in (since + timedelta(days=i) for i in range(14))
    ]
    max_minutes = max([d["minutes"] for d in daily] + [30])

    # 今日(未記録なら昨日)から遡った連続記録日数
    streak = 0
    cursor = today if today.isoformat() in active_days else today - timedelta(days=1)
    while cursor.isoformat() in active_days:
        streak += 1
        cursor -= timedelta(days=1)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "today": today,
            "goal": goal,
            "week_total": week_total,
            "progress": min(100, round(week_total * 100 / goal)) if goal else 0,
            "by_category": by_category,
            "daily": daily,
            "max_minutes": max_minutes,
            "streak": streak,
            "recent": recent,
            "top_exercises": top_exercises,
            "news": news,
            "unread": unread,
        },
    )


@app.post("/settings/goal")
def update_goal(weekly_goal_min: int = Form(...)):
    if weekly_goal_min < 1:
        raise HTTPException(400, "目標は 1 分以上にしてください")
    with db.get_conn() as conn:
        db.set_setting(conn, "weekly_goal_min", str(weekly_goal_min))
    return redirect("/")


# ---------------------------------------------------------------- 運動記録


def _validate_activity(category: str, intensity: str, duration_min: int, activity_date: str):
    if category not in db.CATEGORIES:
        raise HTTPException(400, "カテゴリが不正です")
    if intensity not in db.INTENSITIES:
        raise HTTPException(400, "強度が不正です")
    if duration_min < 1:
        raise HTTPException(400, "時間は 1 分以上にしてください")
    try:
        date.fromisoformat(activity_date)
    except ValueError:
        raise HTTPException(400, "日付が不正です")


def _optional_int(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise HTTPException(400, "カロリーは数値で入力してください")


@app.get("/activities", response_class=HTMLResponse)
def list_activities(request: Request, month: str | None = None, category: str | None = None):
    month = month or date.today().strftime("%Y-%m")
    where = ["substr(date, 1, 7) = ?"]
    params: list = [month]
    if category:
        where.append("category = ?")
        params.append(category)
    with db.get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM activities WHERE {' AND '.join(where)} ORDER BY date DESC, id DESC",
            params,
        ).fetchall()
        exercises = [
            r["exercise"]
            for r in conn.execute(
                "SELECT exercise FROM activities GROUP BY exercise ORDER BY COUNT(*) DESC LIMIT 30"
            ).fetchall()
        ]
    y, m = map(int, month.split("-"))
    prev_month = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
    next_month = f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"
    return templates.TemplateResponse(
        request,
        "activities.html",
        {
            "rows": rows,
            "month": month,
            "prev_month": prev_month,
            "next_month": next_month,
            "category": category or "",
            "total_minutes": sum(r["duration_min"] for r in rows),
            "total_calories": sum(r["calories"] or 0 for r in rows),
            "exercises": exercises,
            "today": date.today().isoformat(),
            "edit": None,
        },
    )


@app.post("/activities")
def create_activity(
    activity_date: str = Form(...),
    category: str = Form(...),
    exercise: str = Form(...),
    duration_min: int = Form(...),
    intensity: str = Form("普通"),
    calories: str = Form(""),
    notes: str = Form(""),
):
    _validate_activity(category, intensity, duration_min, activity_date)
    calories = _optional_int(calories)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO activities (date, category, exercise, duration_min, intensity, calories, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (activity_date, category, exercise.strip(), duration_min, intensity, calories, notes.strip()),
        )
    return redirect(f"/activities?month={activity_date[:7]}")


@app.get("/activities/{activity_id}/edit", response_class=HTMLResponse)
def edit_activity(request: Request, activity_id: int):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
    if not row:
        raise HTTPException(404, "記録が見つかりません")
    return templates.TemplateResponse(request, "activity_edit.html", {"edit": row, "exercises": []})


@app.post("/activities/{activity_id}")
def update_activity(
    activity_id: int,
    activity_date: str = Form(...),
    category: str = Form(...),
    exercise: str = Form(...),
    duration_min: int = Form(...),
    intensity: str = Form("普通"),
    calories: str = Form(""),
    notes: str = Form(""),
):
    _validate_activity(category, intensity, duration_min, activity_date)
    calories = _optional_int(calories)
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE activities SET date = ?, category = ?, exercise = ?, duration_min = ?, "
            "intensity = ?, calories = ?, notes = ? WHERE id = ?",
            (activity_date, category, exercise.strip(), duration_min, intensity, calories,
             notes.strip(), activity_id),
        )
    return redirect(f"/activities?month={activity_date[:7]}")


@app.post("/activities/{activity_id}/delete")
def delete_activity(activity_id: int):
    with db.get_conn() as conn:
        row = conn.execute("SELECT date FROM activities WHERE id = ?", (activity_id,)).fetchone()
        conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,))
    return redirect(f"/activities?month={row['date'][:7]}" if row else "/activities")


# ---------------------------------------------------------------- 情報収集


@app.get("/news", response_class=HTMLResponse)
def list_news(
    request: Request,
    q: str = "",
    category: str = "",
    source_id: str = "",
    view: str = "all",
    page: int = 1,
    msg: str = "",
):
    where = ["1 = 1"]
    params: list = []
    if q:
        where.append("(a.title LIKE ? OR a.summary LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if category:
        where.append("s.category = ?")
        params.append(category)
    if source_id.isdigit():
        where.append("a.source_id = ?")
        params.append(int(source_id))
    if view == "unread":
        where.append("a.is_read = 0")
    elif view == "favorite":
        where.append("a.is_favorite = 1")
    page = max(page, 1)
    sql_where = " AND ".join(where)
    with db.get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM articles a JOIN sources s ON s.id = a.source_id WHERE {sql_where}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT a.*, s.name AS source_name, s.category FROM articles a "
            f"JOIN sources s ON s.id = a.source_id WHERE {sql_where} "
            "ORDER BY COALESCE(a.published_at, a.fetched_at) DESC, a.id DESC LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
        ).fetchall()
        sources = conn.execute("SELECT id, name FROM sources ORDER BY name").fetchall()
    return templates.TemplateResponse(
        request,
        "news.html",
        {
            "rows": rows,
            "total": total,
            "page": page,
            "pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
            "q": q,
            "category": category,
            "source_id": source_id,
            "view": view,
            "sources": sources,
            "msg": msg,
        },
    )


@app.get("/news/{article_id}/open")
def open_article(article_id: int):
    with db.get_conn() as conn:
        row = conn.execute("SELECT link FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "記事が見つかりません")
        conn.execute("UPDATE articles SET is_read = 1 WHERE id = ?", (article_id,))
    return RedirectResponse(row["link"], status_code=302)


@app.post("/news/{article_id}/favorite")
def toggle_favorite(request: Request, article_id: int):
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE articles SET is_favorite = 1 - is_favorite WHERE id = ?", (article_id,)
        )
    return redirect(request.headers.get("referer") or "/news")


@app.post("/news/{article_id}/read")
def toggle_read(request: Request, article_id: int):
    with db.get_conn() as conn:
        conn.execute("UPDATE articles SET is_read = 1 - is_read WHERE id = ?", (article_id,))
    return redirect(request.headers.get("referer") or "/news")


@app.post("/news/mark-all-read")
def mark_all_read():
    with db.get_conn() as conn:
        conn.execute("UPDATE articles SET is_read = 1 WHERE is_read = 0")
    return redirect("/news")


@app.post("/news/collect")
def collect_now(request: Request, source_id: int | None = Form(None)):
    result = collector.collect_all(source_id)
    msg = f"{result['sources']}件の情報源から{result['added']}件の新着を取得"
    if result["errors"]:
        msg += f"(エラー{result['errors']}件)"
    back = "/sources" if source_id else "/news"
    return redirect(f"{back}?msg={msg}")


# ---------------------------------------------------------------- 情報源


@app.get("/sources", response_class=HTMLResponse)
def list_sources(request: Request, msg: str = ""):
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM articles a WHERE a.source_id = s.id) AS article_count "
            "FROM sources s ORDER BY s.id"
        ).fetchall()
    return templates.TemplateResponse(request, "sources.html", {"rows": rows, "msg": msg})


@app.post("/sources")
def create_source(
    category: str = Form(...),
    name: str = Form(""),
    url: str = Form(""),
    keyword: str = Form(""),
):
    if category not in db.CATEGORIES:
        raise HTTPException(400, "カテゴリが不正です")
    keyword = keyword.strip()
    url = url.strip()
    if keyword:
        url = db.google_news_url(keyword)
        name = name.strip() or f"Googleニュース: {keyword}"
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL かキーワードを入力してください")
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO sources (name, url, category) VALUES (?, ?, ?)",
            (name.strip() or url, url, category),
        )
        source_id = cur.lastrowid if cur.rowcount else None
    if source_id:
        collector.collect_all(source_id)
    return redirect("/sources")


@app.post("/sources/{source_id}/toggle")
def toggle_source(source_id: int):
    with db.get_conn() as conn:
        conn.execute("UPDATE sources SET enabled = 1 - enabled WHERE id = ?", (source_id,))
    return redirect("/sources")


@app.post("/sources/{source_id}/delete")
def delete_source(source_id: int):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    return redirect("/sources")
