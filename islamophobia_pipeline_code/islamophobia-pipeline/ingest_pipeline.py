#!/usr/bin/env python3
"""
Hate-incident ingestion pipeline:
- Police UK (street-level, outcomes, force aggregates)
- RSS (Tell MAMA, CST, TrueVision)
- PDF parsing with OCR fallback
- Postcode geocoding (postcodes.io API via requests)
- Dedupe: exact UID + fuzzy title+geo
- Writes to Postgres with upsert/no-dup
"""
import time
import hashlib
import json
import re
from datetime import datetime, timedelta
from io import BytesIO
import requests
import feedparser
import pdfplumber
import pytesseract
from PIL import Image
from bs4 import BeautifulSoup
from simhash import Simhash
from urllib.parse import urlparse
from sqlalchemy import create_engine, Table, Column, Integer, String, Float, Date, MetaData, JSON, Index
from sqlalchemy.dialects.postgresql import insert as pg_insert
from ratelimit import limits, sleep_and_retry

# ---------- VARIABLES ----------
POLICE_API_BASE = "https://data.police.uk/api"
# Force geolocations (lat, lon) — Police UK API requires lat/lng, not force name
FORCE_LOCATIONS = {
    "metropolitan": (51.512, -0.128),
    "greater-manchester": (53.474, -2.240),  # Manchester Piccadilly area
    # Fix: some forces need city-centre coords for max coverage
    "london-city": (51.512, -0.090),
    "west-midlands": (52.486, -1.891),
    "west-yorkshire": (53.801, -1.550),
    "south-yorkshire": (53.383, -1.465),
    "merseyside": (53.409, -2.992),
    "thames-valley": (51.753, -1.257),
    "nottinghamshire": (52.953, -1.149),
    "lancashire": (53.765, -2.708),
    "essex": (51.734, 0.474),
    "kent": (51.281, 0.522),
    "surrey": (51.315, -0.560),
    "sussex": (50.820, -0.140),
    "hampshire": (50.928, -1.406),
    "devon-and-cornwall": (50.719, -3.536),
    "avon-and-somerset": (51.441, -2.599),
}
FORCES = list(FORCE_LOCATIONS.keys())
START_DATE = "2025-07"  # Police UK has data from ~July 2025
END_DATE = "2026-03"    # Data lags ~3 months behind
RSS_FEEDS = {
    "tellmama": "https://tellmamauk.org/feed/",
    "cst": "https://cst.org.uk/rss",
    "truevision": "https://www.report-it.org.uk/rss"
}
PDF_SOURCES = {}
DB_URI = "postgresql://pipeline:hate_pipeline_2026@localhost:5432/hate_db"
TABLE_NAME = "incidents"
POSTCODESIO_URL = "https://api.postcodes.io"
POLICE_RATE_PER_SEC = 1
POSTCODESIO_RATE_PER_SEC = 10
# ---------- /VARIABLES ----------

engine = create_engine(DB_URI, pool_pre_ping=True)
meta = MetaData()
incidents = Table(
    TABLE_NAME, meta,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('uid', String, unique=True, index=True),
    Column('source', String),
    Column('source_id', String),
    Column('date', Date),
    Column('category', String),
    Column('subtype', String),
    Column('latitude', Float),
    Column('longitude', Float),
    Column('location_name', String),
    Column('outcome', String),
    Column('title_hash', String, index=True),
    Column('simhash', String, index=True),
    Column('raw', JSON),
)
Index('idx_incidents_date', incidents.c.date)
meta.create_all(engine)


def make_uid(source, source_id, date, lat, lon, category):
    normalized = f"{source}|{source_id}|{date}|{lat or 'NA'}|{lon or 'NA'}|{category or 'NA'}"
    return hashlib.sha256(normalized.encode()).hexdigest()


# Simple polite rate-limited GET wrapper
@sleep_and_retry
@limits(calls=POLICE_RATE_PER_SEC, period=1)
def http_get(url, params=None, headers=None, timeout=30):
    return requests.get(url, params=params, headers=headers, timeout=timeout)


# Police API helpers
def police_crimes_for_force_month(force, ym):
    """Fetch street-level crimes for a force in a given month using lat/lng."""
    lat, lng = FORCE_LOCATIONS.get(force, (51.5, -0.1))
    params = {"lat": lat, "lng": lng, "date": ym}
    url = f"{POLICE_API_BASE}/crimes-street/all-crime"
    r = http_get(url, params=params)
    if r.status_code == 200:
        return r.json()
    return []


def police_outcomes_for_crime(crime_id):
    """Fetch outcomes for a specific crime ID."""
    url = f"{POLICE_API_BASE}/crimes-street/outcomes/{crime_id}"
    r = http_get(url)
    if r.status_code == 200:
        return r.json()
    return None


def police_hate_crimes_for_force(force):
    """Police UK hate crime endpoint — returns hate crime counts per force."""
    try:
        url = f"{POLICE_API_BASE}/hate-crimes/{force}"
        r = http_get(url)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def map_police_record(rec):
    """Map a Police UK API record to our schema."""
    date = rec.get("month")
    loc = rec.get("location") or {}
    lat = lon = None
    try:
        lat = float(loc.get("latitude")) if loc.get("latitude") else None
        lon = float(loc.get("longitude")) if loc.get("longitude") else None
    except Exception:
        pass
    category = rec.get("category")
    street_name = (loc.get("street") or {}).get("name") if loc.get("street") else None
    source_id = rec.get("id") or f"{rec.get('month')}_{lat}_{lon}"
    uid = make_uid("policeuk", source_id, date, lat, lon, category)
    title_string = " ".join(filter(None, [category or "", street_name or "", str(rec.get('id', ''))]))
    sim = Simhash(title_string).value
    return {
        "uid": uid,
        "source": "policeuk",
        "source_id": source_id,
        "date": datetime.strptime(rec.get("month"), "%Y-%m").date() if rec.get("month") else None,
        "category": category,
        "subtype": None,
        "latitude": lat,
        "longitude": lon,
        "location_name": street_name,
        "outcome": None,
        "title_hash": hashlib.sha1(
            ((rec.get('category', '') + (street_name or ''))).encode()
        ).hexdigest(),
        "simhash": str(sim),
        "raw": rec
    }


def insert_incident(conn, item):
    """Upsert — skip on conflict by uid."""
    stmt = pg_insert(incidents).values(**item).on_conflict_do_nothing(index_elements=['uid'])
    conn.execute(stmt)


def backfill_police():
    """Backfill Police UK street crime data month by month, force by force."""
    print("[Police] Starting backfill...")
    year_months = []
    start = datetime.strptime(START_DATE, "%Y-%m")
    end = datetime.strptime(END_DATE, "%Y-%m")
    cur = start
    while cur <= end:
        year_months.append(cur.strftime("%Y-%m"))
        cur = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)

    total = 0
    with engine.begin() as conn:
        for ym in year_months:
            for force in FORCES:
                tries = 0
                while tries < 5:
                    try:
                        recs = police_crimes_for_force_month(force, ym)
                        for r in recs:
                            mapped = map_police_record(r)
                            insert_incident(conn, mapped)
                            total += 1
                        break
                    except Exception as e:
                        tries += 1
                        time.sleep(2 ** tries)
                if tries >= 5:
                    print(f"  Failed {force} {ym}")
        print(f"[Police] Inserted {total} records")


def fetch_rss_feed(url):
    return feedparser.parse(url)


def extract_text_from_html(html):
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "header", "footer", "nav", "aside"]):
        s.decompose()
    return soup.get_text(separator=" ", strip=True)


def pdf_to_text(content_bytes):
    """Extract text from PDF with pdfplumber, fallback to OCR."""
    texts = []
    try:
        with pdfplumber.open(BytesIO(content_bytes)) as pdf:
            for p in pdf.pages:
                t = p.extract_text()
                if t:
                    texts.append(t)
    except Exception:
        pass
    if texts:
        return "\n".join(texts)
    # OCR fallback
    try:
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(content_bytes)
        ocr_texts = []
        for img in images:
            ocr_texts.append(pytesseract.image_to_string(img))
        return "\n".join(ocr_texts)
    except Exception:
        return ""


def geocode_postcode_lookup(text):
    """Find first UK postcode in text and look up via postcodes.io."""
    m = re.search(r"([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})", text, re.I)
    if not m:
        return None, None, None
    pc = m.group(1).strip().upper()
    try:
        time.sleep(0.1)  # rate limit
        r = requests.get(f"{POSTCODESIO_URL}/postcodes/{pc}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            result = data.get("result", {})
            lat = result.get("latitude")
            lon = result.get("longitude")
            out_pc = result.get("postcode")
            return lat, lon, out_pc
    except Exception:
        pass
    return None, None, None


def map_rss_item(feed_name, it):
    """Map a single RSS entry to our schema."""
    title = it.get("title", "")
    link = it.get("link", "")
    published = it.get("published_parsed")
    date = datetime(*published[:6]).date() if published else datetime.utcnow().date()
    content = it.get("summary") or it.get("description") or ""
    lat = lon = postcode = None
    try:
        r = requests.get(link, timeout=15)
        if r.status_code == 200:
            ct = r.headers.get("Content-Type", "").lower()
            if "application/pdf" in ct:
                txt = pdf_to_text(r.content)
                lat, lon, postcode = geocode_postcode_lookup(txt)
                content = txt or content
            else:
                txt = extract_text_from_html(r.text)
                lat, lon, postcode = geocode_postcode_lookup(txt)
                content = txt or content
    except Exception:
        pass
    source_id = link
    uid = make_uid(feed_name, source_id, str(date), lat, lon, "report")
    sim = Simhash(title + (content[:200] if content else "")).value
    return {
        "uid": uid,
        "source": feed_name,
        "source_id": source_id,
        "date": date,
        "category": "report",
        "subtype": None,
        "latitude": lat,
        "longitude": lon,
        "location_name": title,
        "outcome": None,
        "title_hash": hashlib.sha1(title.encode()).hexdigest(),
        "simhash": str(sim),
        "raw": {"title": title, "link": link, "content_snippet": content[:1000]}
    }


def ingest_rss_feeds():
    """Ingest all configured RSS feeds."""
    print("[RSS] Starting RSS ingestion...")
    total = 0
    with engine.begin() as conn:
        for name, feed_url in RSS_FEEDS.items():
            try:
                f = fetch_rss_feed(feed_url)
                for e in f.entries:
                    mapped = map_rss_item(name, e)
                    insert_incident(conn, mapped)
                    total += 1
                print(f"  {name}: {len(f.entries)} entries")
            except Exception as e:
                print(f"  {name} failed: {e}")
    print(f"[RSS] Inserted {total} records")


def ingest_pdfs():
    """Ingest configured PDF sources with OCR fallback."""
    print("[PDF] Starting PDF ingestion...")
    total = 0
    with engine.begin() as conn:
        for name, url in PDF_SOURCES.items():
            try:
                r = requests.get(url, timeout=30)
                if r.status_code == 200:
                    txt = pdf_to_text(r.content)
                    lat, lon, pc = geocode_postcode_lookup(txt)
                    source_id = url
                    date = datetime.utcnow().date()
                    uid = make_uid(name, source_id, str(date), lat, lon, "report")
                    sim = Simhash(txt[:1000] if txt else "").value
                    item = {
                        "uid": uid,
                        "source": name,
                        "source_id": source_id,
                        "date": date,
                        "category": "report",
                        "subtype": None,
                        "latitude": lat,
                        "longitude": lon,
                        "location_name": name,
                        "outcome": None,
                        "title_hash": hashlib.sha1((name + (pc or "")).encode()).hexdigest(),
                        "simhash": str(sim),
                        "raw": {"text_snippet": txt[:2000]}
                    }
                    insert_incident(conn, item)
                    total += 1
                    print(f"  {name}: PDF ingested ({len(txt)} chars)")
            except Exception as e:
                print(f"  {name} failed: {e}")
    print(f"[PDF] Inserted {total} records")


def police_hate_crime_backfill():
    """Fetch hate crime data from Police UK hate crime endpoint."""
    print("[Police Hate] Starting hate crime aggregation...")
    total = 0
    with engine.begin() as conn:
        for force in FORCES:
            try:
                recs = police_hate_crimes_for_force(force)
                for r in recs:
                    date_str = r.get("month") or r.get("date") or datetime.utcnow().strftime("%Y-%m")
                    if len(date_str) == 7:
                        dt = datetime.strptime(date_str, "%Y-%m").date()
                    else:
                        dt = datetime.utcnow().date()
                    source_id = f"hate_{force}_{date_str}"
                    uid = make_uid("policeuk_hate", source_id, str(dt), None, None, r.get("category", "hate_crime"))
                    sim = Simhash(f"{force} {date_str} {r.get('category', '')} {r.get('count', 0)}").value
                    item = {
                        "uid": uid,
                        "source": "policeuk_hate",
                        "source_id": source_id,
                        "date": dt,
                        "category": "hate_crime",
                        "subtype": r.get("offence_type") or r.get("category", ""),
                        "latitude": None,
                        "longitude": None,
                        "location_name": f"Force: {force}",
                        "outcome": None,
                        "title_hash": hashlib.sha1(f"{force}_{date_str}".encode()).hexdigest(),
                        "simhash": str(sim),
                        "raw": r
                    }
                    insert_incident(conn, item)
                    total += 1
            except Exception as e:
                print(f"  Hate {force} failed: {e}")
    print(f"[Police Hate] Inserted {total} records")


def fuzzy_dedupe():
    """Simple fuzzy dedupe: flag similar titles on same date by simhash distance."""
    print("[Dedup] Running fuzzy deduplication...")
    flagged = 0
    with engine.begin() as conn:
        rows = conn.execute(
            incidents.select().where(incidents.c.latitude == None)
        ).fetchall()
        for r in rows:
            if r.latitude is not None:
                continue
            candidates = conn.execute(
                incidents.select().where(incidents.c.date == r.date).limit(50)
            ).fetchall()
            for c in candidates:
                if c.uid == r.uid or c.latitude is not None:
                    continue
                try:
                    sim_dist = abs(int(r.simhash) - int(c.simhash))
                except Exception:
                    sim_dist = 1000000
                if sim_dist < 2000:
                    # Mark the lower-priority source as a duplicate
                    priority = {"policeuk": 3, "policeuk_hate": 3, "cst": 2, "tellmama": 2}
                    r_prio = priority.get(r.source, 1)
                    c_prio = priority.get(c.source, 1)
                    drop = c if r_prio >= c_prio else r
                    current = conn.execute(
                        incidents.select().where(incidents.c.uid == drop.uid)
                    ).fetchone()
                    if current and current.raw:
                        updated_raw = dict(current.raw)
                        updated_raw["dedupe_note"] = "marked_duplicate"
                        conn.execute(
                            incidents.update().where(incidents.c.uid == drop.uid).values(
                                raw=updated_raw
                            )
                        )
                        flagged += 1
                    break
    print(f"[Dedup] Flagged {flagged} duplicates")


def get_stats():
    """Print quick stats from the DB."""
    with engine.connect() as conn:
        total = conn.execute(incidents.count()).scalar()
        by_source = conn.execute(
            "SELECT source, COUNT(*) FROM incidents GROUP BY source ORDER BY COUNT(*) DESC LIMIT 10"
        ).fetchall()
        by_date = conn.execute(
            "SELECT date, COUNT(*) FROM incidents GROUP BY date ORDER BY date DESC LIMIT 10"
        ).fetchall()
        hate_count = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE category LIKE '%hate%' OR category LIKE '%racial%' OR category LIKE '%religi%'"
        ).scalar()
    print(f"\n{'='*50}")
    print(f"Total incidents: {total}")
    print(f"Hate/racial/religious flagged: {hate_count}")
    print(f"\nTop sources:")
    for s, c in by_source:
        print(f"  {s}: {c}")
    print(f"\nRecent dates:")
    for d, c in by_date:
        print(f"  {d}: {c}")
    print(f"{'='*50}")


def run_all():
    """Run the full ingestion pipeline."""
    t0 = time.time()
    print(f"[Pipeline] Started at {datetime.utcnow().isoformat()}")
    print(f"[Pipeline] Backfill window: {START_DATE} to {END_DATE}")
    print(f"[Pipeline] Forces: {len(FORCES)}")
    print(f"[Pipeline] RSS feeds: {len(RSS_FEEDS)}")
    print()
    backfill_police()
    print()
    police_hate_crime_backfill()
    print()
    ingest_rss_feeds()
    print()
    ingest_pdfs()
    print()
    fuzzy_dedupe()
    print()
    get_stats()
    elapsed = time.time() - t0
    print(f"\n[Pipeline] Complete in {elapsed:.1f}s")


if __name__ == "__main__":
    run_all()
