import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import pandas as pd

SCHEMA_PATH = "db_schema.sql"
DB_PATH = "output/islamophobia_v3.sqlite3"
KEYWORDS = ["islamophobia", "anti-muslim", "anti muslim", "muslim hate", "hate crime", "tell mama", "iru"]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(db_path: str = DB_PATH, schema_path: str = SCHEMA_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    schema = Path(schema_path).read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()
    return conn


def make_id(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()


def normalize_text(text):
    return " ".join((text or "").split()).strip()


def relevance_score(text):
    t = (text or "").lower()
    hits = sum(k in t for k in KEYWORDS)
    return round(min(1.0, hits / 3), 3)


def upsert_source(conn, source_name, source_type, url, weight=0.5, country="UK", region=None, active=1):
    sid = make_id(source_name, url)
    conn.execute(
        """
        INSERT INTO sources(
            source_id, source_name, source_type, source_weight, url,
            country, region, active, last_fetched_at
        )
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_id) DO UPDATE SET
            source_name=excluded.source_name,
            source_type=excluded.source_type,
            source_weight=excluded.source_weight,
            url=excluded.url,
            country=excluded.country,
            region=excluded.region,
            active=excluded.active,
            last_fetched_at=excluded.last_fetched_at
        """,
        (sid, source_name, source_type, weight, url, country, region, active, now_iso()),
    )
    conn.commit()
    return sid


def upsert_incident(
    conn,
    source_id,
    title,
    summary="",
    content="",
    incident_type="unknown",
    verified=0,
    published_at=None,
    reported_at=None,
    location_text=None,
    confidence=0.0,
    event_flag=0,
    conflict_flag=0,
    protest_flag=0,
    far_right_flag=0,
    offline_flag=0,
    online_flag=0,
    article_url="",  # ← ADDED article_url parameter
):
    text = normalize_text(" ".join([title or "", summary or "", content or ""]))
    incident_id = make_id(source_id, title, published_at, location_text, text[:200])
    score = relevance_score(text)
    location_norm = normalize_text(location_text).lower() if location_text else None
    ts = now_iso()

    conn.execute(
        """
        INSERT INTO incidents(
            incident_id, source_id, source_incident_id, title, summary, content,
            incident_type, verified, published_at, reported_at, location_text,
            location_norm, latitude, longitude, confidence, relevance_score,
            event_flag, conflict_flag, protest_flag, far_right_flag,
            offline_flag, online_flag, article_url, created_at, updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(incident_id) DO UPDATE SET
            title=excluded.title,
            summary=excluded.summary,
            content=excluded.content,
            incident_type=excluded.incident_type,
            verified=excluded.verified,
            published_at=excluded.published_at,
            reported_at=excluded.reported_at,
            location_text=excluded.location_text,
            location_norm=excluded.location_norm,
            confidence=excluded.confidence,
            relevance_score=excluded.relevance_score,
            event_flag=excluded.event_flag,
            conflict_flag=excluded.conflict_flag,
            protest_flag=excluded.protest_flag,
            far_right_flag=excluded.far_right_flag,
            offline_flag=excluded.offline_flag,
            online_flag=excluded.online_flag,
            article_url=excluded.article_url,
            updated_at=excluded.updated_at
        """,
        (
            incident_id,
            source_id,
            None,
            title,
            summary,
            content,
            incident_type,
            verified,
            published_at,
            reported_at,
            location_text,
            location_norm,
            None,
            None,
            confidence,
            score,
            event_flag,
            conflict_flag,
            protest_flag,
            far_right_flag,
            offline_flag,
            online_flag,
            article_url,  # ← ADDED article_url value
            ts,
            ts,
        ),
    )
    conn.commit()
    return incident_id, score


def tag_incident(conn, incident_id, tags):
    for tag in tags:
        conn.execute(
            """
            INSERT INTO incident_tags(incident_id, tag, value)
            VALUES(?,?,1)
            ON CONFLICT(incident_id, tag) DO UPDATE SET value=excluded.value
            """,
            (incident_id, tag),
        )
    conn.commit()


def refresh_daily_metrics(conn):
    df = pd.read_sql_query("SELECT * FROM incidents", conn)
    if df.empty:
        return None

    df["day"] = pd.to_datetime(df["published_at"], errors="coerce").dt.date.astype(str)
    daily = (
        df.groupby(["day"])
        .agg(
            total_incidents=("incident_id", "count"),
            verified_incidents=("verified", "sum"),
            avg_confidence=("confidence", "mean"),
            avg_relevance=("relevance_score", "mean"),
            online_share=("online_flag", "mean"),
            offline_share=("offline_flag", "mean"),
        )
        .reset_index()
    )

    for _, row in daily.iterrows():
        conn.execute(
            """
            INSERT INTO daily_metrics(
                day, source_id, total_items, total_incidents, verified_incidents,
                avg_confidence, avg_relevance, online_share, offline_share, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(day, source_id) DO UPDATE SET
                total_items=excluded.total_items,
                total_incidents=excluded.total_incidents,
                verified_incidents=excluded.verified_incidents,
                avg_confidence=excluded.avg_confidence,
                avg_relevance=excluded.avg_relevance,
                online_share=excluded.online_share,
                offline_share=excluded.offline_share,
                created_at=excluded.created_at
            """,
            (
                row["day"],
                None,
                int(row["total_incidents"]),
                int(row["total_incidents"]),
                int(row["verified_incidents"]),
                float(row["avg_confidence"]),
                float(row["avg_relevance"]),
                float(row["online_share"]),
                float(row["offline_share"]),
                now_iso(),
            ),
        )

    conn.commit()
    return daily
