#!/usr/bin/env python3
"""
Islamophobia Incident Pipeline v3
==================================
Full schema: sources, incidents, incident_tags, daily_metrics, events
ML features: rolling windows, source diversity, temporal, event flags
Weighting: source-type based confidence scoring
Predictive targets: next_day / next_7_day / spike_label

Usage:
    python3 pipeline.py                         # Full run
    python3 pipeline.py --quick                 # Ingest only (no content fetch)
    python3 pipeline.py --features              # Generate feature vectors for ML
    python3 pipeline.py --show-config           # Active configuration
    python3 pipeline.py --alert                 # Breaking alerts
"""

import os, re, json, hashlib, sqlite3, logging, argparse, sys, time
import random
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta, date
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
from urllib.parse import urlparse
from collections import Counter

import requests
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

logging.getLogger('scrapling').setLevel(logging.ERROR)
try:
    from scrapling import Fetcher
    HAS_SCRAPLING = True
except ImportError:
    HAS_SCRAPLING = False

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# ── Config ────────────────────────────────────────────────────────
DB_PATH = os.getenv('PIPELINE_DB', 'output/islamophobia_v3.sqlite3')
OUT_DIR = Path('output')
LOG_DIR = Path('logs')
MODEL_DIR = Path('models')
for d in [OUT_DIR, LOG_DIR, MODEL_DIR]:
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / f'pipeline_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

KEYWORD_THRESHOLD = 0.3
MAX_ARTICLES_PER_SOURCE = 25

# ── Source weighting per spec ─────────────────────────────────────
SOURCE_WEIGHT_MAP = {
    'official': 1.0,
    'advocacy': 0.9,
    'community': 0.85,
    'news': 0.4,
    'social': 0.25,
}
# Map source names to categories
SOURCE_CATEGORY_MAP = {
    'TellMAMA': 'advocacy',
    'IRU': 'advocacy',
    'BBC_RSS_UK': 'news',
    'BBC_RSS_World': 'news',
    'Guardian_RSS': 'news',
    'Guardian_Society': 'news',
    'Guardian_Religion': 'news',
    'SkyNews_RSS': 'news',
    'SkyNews_RSS_Home': 'news',
    'Independent_RSS': 'news',
    'Independent_Voices': 'news',
    'iNews_RSS': 'news',
    'DailyMail_RSS': 'news',
    'DailyMail_News': 'news',
    'Telegraph_News': 'news',
    'AJ_UK_RSS': 'news',
    'GoogleNews_Islamophobia': 'news',
    'GoogleNews_AntiMuslim': 'news',
    'GoogleNews_HateCrime': 'news',
    'GoogleNews_MosqueAttack': 'news',
}

INCIDENT_KEYWORDS = {
    'abuse': ['abuse', 'verbal abuse', 'racial abuse', 'religious abuse'],
    'assault': ['assault', 'attack', 'stab', 'beaten', 'punched', 'kicked'],
    'vandalism': ['vandalism', 'graffiti', 'damage', 'smashed', 'broken window'],
    'threat': ['threat', 'intimidation', 'harassment', 'menaced'],
    'discrimination': ['discrimination', 'bias', 'profiling', 'exclusion'],
    'online': ['online', 'social media', 'twitter', 'tiktok', 'telegram'],
}

KEYWORDS = [
    'islamophobia','anti-muslim','anti muslim','muslim hate','muslim hostility',
    'religious hate','hate crime','tell mama','iru','anti-muslim hate',
    'islamophobic','mosque attack','mosque vandalism','mosque fire',
    'muslim cemetery','hijab attack','religious abuse','faith hate',
    'extremism','far-right','islamist','islamophobia monitor',
    'racial hatred','religiously aggravated','anti-islam',
]

NEGATIVE_KEYWORDS = [
    'football','sport','recipe','weather','tv guide','premier league',
    'cricket','boxing','fashion','finance','stock market','mortgage',
]


# ── Dataclasses ────────────────────────────────────────────────────
@dataclass
class SourceDef:
    name: str
    url: str
    source_type: str = 'rss'
    category: str = 'news'
    country: str = 'UK'
    region: str = ''
    active: bool = True

@dataclass
class Incident:
    incident_id: str
    source_id: str
    source_incident_id: str
    title: str
    summary: str = ''
    content: str = ''
    incident_type: str = 'discrimination'
    verified: bool = False
    published_at: Optional[str] = None
    reported_at: Optional[str] = None
    location_text: str = ''
    location_norm: str = ''
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    confidence: float = 0.0
    relevance_score: float = 0.0
    event_flag: int = 0
    conflict_flag: int = 0
    protest_flag: int = 0
    far_right_flag: int = 0
    offline_flag: int = 0
    online_flag: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def clean_text(text: str) -> str:
    return ' '.join((text or '').split())

def sha1(text: str) -> str:
    return hashlib.sha1((text or '').encode('utf-8')).hexdigest()

def gen_id() -> str:
    return uuid.uuid4().hex[:16]

def extract_text(html: str) -> str:
    if not html:
        return ''
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script','style','noscript','nav','footer','header']):
        tag.decompose()
    return clean_text(soup.get_text(' ', strip=True))

def extract_title(html: str) -> Optional[str]:
    m = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
    return clean_text(m.group(1)) if m else None

def score_relevance(text: str) -> float:
    t = (text or '').lower()
    if not t:
        return 0.0
    hits = sum(1 for k in KEYWORDS if k in t)
    neg = sum(1 for k in NEGATIVE_KEYWORDS if k in t)
    segs = re.split(r'[.…!?\n]{2,}', t)
    conc = sum(1 for s in segs if sum(1 for k in KEYWORDS if k in s) >= 2)
    base = hits / max(5, len(KEYWORDS) / 4)
    penalty = neg / max(5, len(NEGATIVE_KEYWORDS))
    bonus = conc * 0.15
    return round(max(0.0, min(1.0, base - penalty + bonus)), 3)

def classify_incident_type(text: str) -> str:
    t = (text or '').lower()
    best_type = 'discrimination'
    best_score = 0
    for itype, patterns in INCIDENT_KEYWORDS.items():
        score = sum(1 for p in patterns if p in t)
        if score > best_score:
            best_score = score
            best_type = itype
    return best_type


# ── DB Schema ──────────────────────────────────────────────────────
def init_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            source_name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_weight REAL NOT NULL DEFAULT 0.5,
            url TEXT NOT NULL,
            country TEXT,
            region TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            last_fetched_at TEXT
        );

        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            event_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT,
            location_text TEXT,
            impact_window_days INTEGER NOT NULL DEFAULT 14,
            source_url TEXT
        );

        CREATE TABLE IF NOT EXISTS incidents (
            incident_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            source_incident_id TEXT,
            title TEXT,
            summary TEXT,
            content TEXT,
            incident_type TEXT,
            verified INTEGER NOT NULL DEFAULT 0,
            published_at TEXT,
            reported_at TEXT,
            location_text TEXT,
            location_norm TEXT,
            latitude REAL,
            longitude REAL,
            confidence REAL NOT NULL DEFAULT 0,
            relevance_score REAL NOT NULL DEFAULT 0,
            event_flag INTEGER NOT NULL DEFAULT 0,
            conflict_flag INTEGER NOT NULL DEFAULT 0,
            protest_flag INTEGER NOT NULL DEFAULT 0,
            far_right_flag INTEGER NOT NULL DEFAULT 0,
            offline_flag INTEGER NOT NULL DEFAULT 0,
            online_flag INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        );

        CREATE INDEX IF NOT EXISTS idx_incidents_source_id ON incidents(source_id);
        CREATE INDEX IF NOT EXISTS idx_incidents_published_at ON incidents(published_at);
        CREATE INDEX IF NOT EXISTS idx_incidents_reported_at ON incidents(reported_at);
        CREATE INDEX IF NOT EXISTS idx_incidents_location_norm ON incidents(location_norm);
        CREATE INDEX IF NOT EXISTS idx_incidents_event_flag ON incidents(event_flag);
        CREATE INDEX IF NOT EXISTS idx_incidents_relevance ON incidents(relevance_score);

        CREATE TABLE IF NOT EXISTS incident_tags (
            incident_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            value INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (incident_id, tag),
            FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
        );

        CREATE TABLE IF NOT EXISTS daily_metrics (
            day TEXT NOT NULL,
            source_id TEXT,
            total_items INTEGER NOT NULL DEFAULT 0,
            total_incidents INTEGER NOT NULL DEFAULT 0,
            verified_incidents INTEGER NOT NULL DEFAULT 0,
            avg_confidence REAL NOT NULL DEFAULT 0,
            avg_relevance REAL NOT NULL DEFAULT 0,
            online_share REAL NOT NULL DEFAULT 0,
            offline_share REAL NOT NULL DEFAULT 0,
            created_at TEXT,
            PRIMARY KEY (day, source_id)
        );

        CREATE TABLE IF NOT EXISTS model_runs (
            run_id TEXT PRIMARY KEY,
            model_name TEXT NOT NULL,
            train_start TEXT,
            train_end TEXT,
            test_start TEXT,
            test_end TEXT,
            features_json TEXT,
            metrics_json TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_start TEXT,
            run_end TEXT,
            items_fetched INTEGER,
            new_items INTEGER,
            avg_relevance REAL,
            status TEXT
        );
    """)
    conn.commit()
    return conn


# ── Source Management ──────────────────────────────────────────────
DEFAULT_SOURCES = [
    SourceDef('TellMAMA', 'https://tellmamauk.org', 'html', 'advocacy'),
    SourceDef('IRU', 'https://www.theiru.org.uk', 'html', 'advocacy'),
    SourceDef('BBC_RSS_UK', 'https://feeds.bbci.co.uk/news/uk/rss.xml'),
    SourceDef('BBC_RSS_World', 'https://feeds.bbci.co.uk/news/world/rss.xml'),
    SourceDef('Guardian_RSS', 'https://www.theguardian.com/uk/rss'),
    SourceDef('Guardian_Society', 'https://www.theguardian.com/society/rss'),
    SourceDef('Guardian_Religion', 'https://www.theguardian.com/world/religion/rss'),
    SourceDef('SkyNews_RSS', 'https://feeds.skynews.com/feeds/rss/uk.xml'),
    SourceDef('SkyNews_RSS_Home', 'https://feeds.skynews.com/feeds/rss/home.xml'),
    SourceDef('Independent_RSS', 'https://www.independent.co.uk/rss'),
    SourceDef('Independent_Voices', 'https://www.independent.co.uk/voices/rss'),
    SourceDef('iNews_RSS', 'https://inews.co.uk/feed'),
    SourceDef('DailyMail_RSS', 'https://www.dailymail.co.uk/articles.rss'),
    SourceDef('DailyMail_News', 'https://www.dailymail.co.uk/news/index.rss'),
    SourceDef('Telegraph_News', 'https://www.telegraph.co.uk/news/rss.xml'),
    SourceDef('AJ_UK_RSS', 'https://www.aljazeera.com/xml/rss/all.xml'),
    SourceDef('GoogleNews_Islamophobia', 'https://news.google.com/rss/search?q=islamophobia+UK&hl=en-GB&gl=GB&ceid=GB:en'),
    SourceDef('GoogleNews_AntiMuslim', 'https://news.google.com/rss/search?q=%22anti-Muslim%22+hate+crime+UK&hl=en-GB&gl=GB&ceid=GB:en'),
    SourceDef('GoogleNews_HateCrime', 'https://news.google.com/rss/search?q=%22hate+crime%22+muslim+UK&hl=en-GB&gl=GB&ceid=GB:en'),
    SourceDef('GoogleNews_MosqueAttack', 'https://news.google.com/rss/search?q=mosque+attack+vandalism+UK&hl=en-GB&gl=GB&ceid=GB:en'),
    # Additional sources for better coverage
    SourceDef('GoogleNews_MuslimUK', 'https://news.google.com/rss/search?q=muslim+UK+hate+crime+attack&hl=en-GB&gl=GB&ceid=GB:en'),
    SourceDef('GoogleNews_FarRight', 'https://news.google.com/rss/search?q=%22far-right%22+UK+attack+protest&hl=en-GB&gl=GB&ceid=GB:en'),
    SourceDef('GoogleNews_Racism', 'https://news.google.com/rss/search?q=racial+hate+crime+UK+police&hl=en-GB&gl=GB&ceid=GB:en'),
    SourceDef('MEND', 'https://www.mend.org.uk/feed/', 'rss', 'advocacy'),
    SourceDef('MCB', 'https://mcb.org.uk/feed/', 'rss', 'advocacy'),
    SourceDef('HopeNotHate', 'https://hopenothate.org.uk/feed/', 'rss', 'advocacy'),
    SourceDef('StopHateUK', 'https://www.stophateuk.org/feed/', 'rss', 'advocacy'),
    SourceDef('TheCanary', 'https://www.thecanary.co/feed/', 'rss', 'news'),
    SourceDef('NovaraMedia', 'https://novaramedia.com/feed/', 'rss', 'news'),
    SourceDef('BylineTimes', 'https://bylinetimes.com/feed/', 'rss', 'news'),
    SourceDef('PoliceUK_HateCrime', 'https://www.police.uk/pu/notices/hate-crime/', 'rss', 'official'),
]


def ensure_sources(conn, sources: List[SourceDef] = None):
    """Ensure all source definitions exist in the DB."""
    sources = sources or DEFAULT_SOURCES
    c = conn.cursor()
    for src in sources:
        cat = src.category
        weight = SOURCE_WEIGHT_MAP.get(cat, 0.4)
        sid = sha1(src.name)
        c.execute("""
            INSERT OR IGNORE INTO sources(source_id, source_name, source_type, source_weight, url, country, region, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (sid, src.name, cat, weight, src.url, src.country, src.region, int(src.active)))
    conn.commit()
    return {src.name: sha1(src.name) for src in sources}


# ── Fetching ───────────────────────────────────────────────────────
def fetch_with_retry(url: str, timeout: int = 20, max_retries: int = 2) -> str:
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; IslamophobiaPipeline/3.0)'}
    if HAS_SCRAPLING:
        try:
            fetcher = Fetcher()
            resp = fetcher.get(url, timeout=timeout)
            if resp and resp.status == 200 and len((resp.text or '')) > 100:
                return resp.text
        except Exception:
            pass
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
    raise last_exc or RuntimeError(f"Failed after {max_retries} attempts")


# ── Source Parsing ─────────────────────────────────────────────────
def parse_rss(source_name: str, rss_url: str, max_items: int = None) -> List[Incident]:
    max_items = max_items or MAX_ARTICLES_PER_SOURCE
    items: List[Incident] = []
    sid = sha1(source_name)

    if HAS_FEEDPARSER:
        try:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries[:max_items]:
                url = entry.get('link', '')
                if not url:
                    continue
                title = clean_text(entry.get('title', 'Untitled'))
                summary = clean_text(entry.get('summary', ''))
                published = entry.get('published') or entry.get('updated')
                text_for_scoring = f"{title} {summary} {source_name}"
                rel = score_relevance(text_for_scoring)
                itype = classify_incident_type(text_for_scoring)
                is_online = 1 if any(k in text_for_scoring.lower() for k in INCIDENT_KEYWORDS['online']) else 0
                is_offline = 1 if itype in ('assault','vandalism','threat','abuse') else 0

                items.append(Incident(
                    incident_id=gen_id(),
                    source_id=sid,
                    source_incident_id=sha1(url),
                    title=title,
                    summary=summary,
                    content=summary,
                    incident_type=itype,
                    published_at=published,
                    reported_at=now_iso(),
                    relevance_score=rel,
                    confidence=rel,
                    online_flag=is_online,
                    offline_flag=is_offline,
                    protest_flag=1 if any(k in text_for_scoring.lower() for k in ['protest','march','rally']) else 0,
                    conflict_flag=1 if any(k in text_for_scoring.lower() for k in ['gaza','israel','palestine','hamas']) else 0,
                    far_right_flag=1 if any(k in text_for_scoring.lower() for k in ['far-right','edl','britain first','patriotic alternative']) else 0,
                    event_flag=0,
                    created_at=now_iso(),
                    updated_at=now_iso(),
                ))
            log.info(f"[RSS] {source_name}: {len(items)} articles")
            return items
        except Exception as e:
            log.warning(f"[RSS] feedparser failed {source_name}: {e}")

    # Fallback
    try:
        xml_data = fetch_with_retry(rss_url)
    except Exception as e:
        log.error(f"[RSS] {source_name}: fetch failed: {e}")
        return items
    soup = BeautifulSoup(xml_data, 'xml')
    entries = soup.find_all('item') or soup.find_all('entry')
    for entry in entries[:max_items]:
        title_tag = entry.find('title')
        link_tag = entry.find('link')
        pub_tag = entry.find('pubDate') or entry.find('published') or entry.find('updated')
        title = clean_text(title_tag.get_text(strip=True)) if title_tag else 'Untitled'
        url = ''
        if link_tag:
            url = link_tag.get('href', '').strip() or clean_text(link_tag.get_text(strip=True))
        published = clean_text(pub_tag.get_text(strip=True)) if pub_tag else None
        if not url:
            continue
        text_for_scoring = f"{title} {source_name}"
        rel = score_relevance(text_for_scoring)
        itype = classify_incident_type(text_for_scoring)
        items.append(Incident(
            incident_id=gen_id(), source_id=sid, source_incident_id=sha1(url),
            title=title, incident_type=itype, published_at=published,
            reported_at=now_iso(), relevance_score=rel, confidence=rel,
            online_flag=1 if any(k in text_for_scoring.lower() for k in INCIDENT_KEYWORDS['online']) else 0,
            offline_flag=1 if itype in ('assault','vandalism','threat','abuse') else 0,
            protest_flag=1 if any(k in text_for_scoring.lower() for k in ['protest','march']) else 0,
            conflict_flag=1 if any(k in text_for_scoring.lower() for k in ['gaza','israel','palestine']) else 0,
            far_right_flag=1 if any(k in text_for_scoring.lower() for k in ['far-right','edl']) else 0,
            created_at=now_iso(), updated_at=now_iso(),
        ))
    log.info(f"[RSS] {source_name}: {len(items)} articles (BS4)")
    return items


def parse_html(source_name: str, url: str) -> List[Incident]:
    sid = sha1(source_name)
    try:
        html_text = fetch_with_retry(url)
        text = extract_text(html_text)
        title = extract_title(html_text) or source_name
        rel = score_relevance(f"{title} {text} {source_name}")
        itype = classify_incident_type(f"{title} {text}")
        return [Incident(
            incident_id=gen_id(), source_id=sid, source_incident_id=sha1(url),
            title=title, content=text, incident_type=itype,
            reported_at=now_iso(), relevance_score=rel, confidence=rel,
            online_flag=0, offline_flag=1,
            created_at=now_iso(), updated_at=now_iso(),
        )]
    except Exception as e:
        log.warning(f"[HTML] {source_name}: {e}")
        return []


# ── Ingest ─────────────────────────────────────────────────────────
def ingest(conn, quick: bool = False) -> Tuple[int, int]:
    """Ingest all sources. Returns (total, new_count)."""
    # Map source names to IDs
    c = conn.cursor()
    c.execute("SELECT source_name, source_id FROM sources WHERE active=1")
    name_to_id = {r[0]: r[1] for r in c.fetchall()}
    c.execute("SELECT source_id, source_name FROM sources WHERE active=1")
    id_to_name = {r[0]: r[1] for r in c.fetchall()}

    all_incidents: List[Incident] = []
    for src in DEFAULT_SOURCES:
        if not src.active:
            continue
        sid = name_to_id.get(src.name, sha1(src.name))
        try:
            if src.source_type == 'rss':
                items = parse_rss(src.name, src.url)
            else:
                items = parse_html(src.name, src.url)
            all_incidents.extend(items)
        except Exception as e:
            log.error(f"[{src.name}] Error: {e}")

    log.info(f"Total ingested: {len(all_incidents)} items")

    # DB upsert
    new_count = 0
    for inc in all_incidents:
        c.execute("SELECT 1 FROM incidents WHERE source_incident_id=? AND source_id=?",
                  (inc.source_incident_id, inc.source_id))
        exists = c.fetchone() is not None
        if not exists:
            new_count += 1
        c.execute("""
            INSERT INTO incidents(
                incident_id, source_id, source_incident_id, title, summary, content,
                incident_type, verified, published_at, reported_at,
                location_text, location_norm, latitude, longitude,
                confidence, relevance_score,
                event_flag, conflict_flag, protest_flag, far_right_flag,
                offline_flag, online_flag, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(incident_id) DO UPDATE SET
                title=excluded.title, summary=excluded.summary, content=excluded.content,
                incident_type=excluded.incident_type, relevance_score=excluded.relevance_score,
                confidence=excluded.confidence, updated_at=excluded.updated_at
        """, (
            inc.incident_id, inc.source_id, inc.source_incident_id,
            inc.title, inc.summary, inc.content,
            inc.incident_type, int(inc.verified), inc.published_at, inc.reported_at,
            inc.location_text, inc.location_norm, inc.latitude, inc.longitude,
            inc.confidence, inc.relevance_score,
            inc.event_flag, inc.conflict_flag, inc.protest_flag, inc.far_right_flag,
            inc.offline_flag, inc.online_flag, inc.created_at, inc.updated_at,
        ))
    conn.commit()

    # Update last_fetched_at for sources
    now = now_iso()
    for src in DEFAULT_SOURCES:
        sid = name_to_id.get(src.name, sha1(src.name))
        c.execute("UPDATE sources SET last_fetched_at=? WHERE source_id=?", (now, sid))
    conn.commit()

    return len(all_incidents), new_count


# ── Daily Metrics ──────────────────────────────────────────────────
def build_daily_metrics(conn) -> Dict:
    try:
        df = pd.read_sql_query("SELECT * FROM incidents", conn)
    except Exception:
        return None
    if df.empty:
        return None

    day = datetime.now().date().isoformat()
    c = conn.cursor()

    total = int(len(df))
    incidents_total = int((df['relevance_score'].fillna(0) >= KEYWORD_THRESHOLD).sum())
    verified = int(df['verified'].sum()) if 'verified' in df else 0
    avg_conf = float(df['confidence'].fillna(0).mean())
    avg_rel = float(df['relevance_score'].fillna(0).mean())
    online_share = float(df['online_flag'].mean()) if 'online_flag' in df else 0.0
    offline_share = float(df['offline_flag'].mean()) if 'offline_flag' in df else 0.0

    # Per-source metrics
    if 'source_id' in df:
        for sid, grp in df.groupby('source_id'):
            c.execute("""
                INSERT INTO daily_metrics(day, source_id, total_items, total_incidents,
                    verified_incidents, avg_confidence, avg_relevance, online_share, offline_share, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(day, source_id) DO UPDATE SET
                    total_items=excluded.total_items, total_incidents=excluded.total_incidents,
                    verified_incidents=excluded.verified_incidents, avg_confidence=excluded.avg_confidence,
                    avg_relevance=excluded.avg_relevance, online_share=excluded.online_share,
                    offline_share=excluded.offline_share, created_at=excluded.created_at
            """, (day, sid, len(grp), int((grp['relevance_score'] >= KEYWORD_THRESHOLD).sum()),
                  int(grp['verified'].sum()) if 'verified' in grp else 0,
                  float(grp['confidence'].mean()), float(grp['relevance_score'].mean()),
                  float(grp['online_flag'].mean()) if 'online_flag' in grp else 0.0,
                  float(grp['offline_flag'].mean()) if 'offline_flag' in grp else 0.0,
                  now_iso()))
    else:
        c.execute("""
            INSERT INTO daily_metrics(day, source_id, total_items, total_incidents,
                verified_incidents, avg_confidence, avg_relevance, online_share, offline_share, created_at)
            VALUES (?,NULL,?,?,?,?,?,?,?,?)
            ON CONFLICT(day, source_id) DO UPDATE SET
                total_items=excluded.total_items, total_incidents=excluded.total_incidents,
                verified_incidents=excluded.verified_incidents, avg_confidence=excluded.avg_confidence,
                avg_relevance=excluded.avg_relevance, online_share=excluded.online_share,
                offline_share=excluded.offline_share, created_at=excluded.created_at
        """, (day, total, incidents_total, verified, avg_conf, avg_rel, online_share, offline_share, now_iso()))

    conn.commit()
    result = {
        'day': day, 'total_items': total, 'incidents': incidents_total,
        'verified': verified, 'avg_confidence': round(avg_conf, 3),
        'avg_relevance': round(avg_rel, 3), 'online_share': round(online_share, 3),
        'offline_share': round(offline_share, 3),
    }
    log.info(f"Daily metrics: {json.dumps(result)}")
    return result


# ── Feature Engineering (spec-compliant) ──────────────────────────
FEATURE_COLUMNS = [
    'lag_1_incidents', 'lag_7_incidents', 'lag_14_incidents', 'lag_28_incidents',
    'rolling_7_incidents', 'rolling_28_incidents',
    'rolling_7_verified', 'rolling_28_verified',
    'rolling_7_online_share', 'rolling_28_online_share',
    'rolling_7_confidence',
    'source_mix_entropy', 'source_diversity',
    'event_flag', 'conflict_flag', 'protest_flag', 'far_right_flag',
    'weekend_flag', 'month', 'weekday', 'days_since_event',
    'report_lag_days_mean', 'report_lag_days_median',
]


def compute_features(conn, target_date: Optional[str] = None) -> pd.DataFrame:
    """
    Compute spec-compliant feature vector for ML training/prediction.
    Generates: lags, rolling windows, source diversity, temporal, event proximity, targets.
    """
    df = pd.read_sql_query("""
        SELECT incident_id, source_id, published_at, reported_at, created_at,
               relevance_score, confidence, verified,
               event_flag, conflict_flag, protest_flag, far_right_flag,
               online_flag, offline_flag
        FROM incidents
    """, conn)

    if df.empty:
        return pd.DataFrame()

    # Parse dates — coerce to tz-naive UTC for consistent arithmetic
    for col in ['published_at', 'reported_at', 'created_at']:
        df[col] = pd.to_datetime(df[col], errors='coerce', utc=True).dt.tz_localize(None)

    df['day'] = df['published_at'].dt.date
    is_incident = df['relevance_score'].fillna(0) >= KEYWORD_THRESHOLD

    daily = df.groupby('day').agg(
        total_incidents=pd.NamedAgg(column='relevance_score', aggfunc=lambda x: (x >= KEYWORD_THRESHOLD).sum()),
        total_verified=pd.NamedAgg(column='verified', aggfunc='sum'),
        total_online=pd.NamedAgg(column='online_flag', aggfunc='sum'),
        total_offline=pd.NamedAgg(column='offline_flag', aggfunc='sum'),
        avg_confidence=pd.NamedAgg(column='confidence', aggfunc='mean'),
        source_ids=pd.NamedAgg(column='source_id', aggfunc=lambda x: list(x)),
    ).reset_index()
    daily = daily.sort_values('day')
    daily['total_items'] = df.groupby('day').size().values
    daily['online_share'] = (daily['total_online'] / daily['total_items']).fillna(0)
    daily['offline_share'] = (daily['total_offline'] / daily['total_items']).fillna(0)

    # Lags
    for lag in [1, 7, 14, 28]:
        daily[f'lag_{lag}_incidents'] = daily['total_incidents'].shift(lag)

    # Rolling windows
    for w in [7, 28]:
        daily[f'rolling_{w}_incidents'] = daily['total_incidents'].rolling(w, min_periods=1).mean()
        daily[f'rolling_{w}_verified'] = daily['total_verified'].rolling(w, min_periods=1).mean()
        daily[f'rolling_{w}_online_share'] = daily['online_share'].rolling(w, min_periods=1).mean()
        daily[f'rolling_{w}_confidence'] = daily['avg_confidence'].rolling(w, min_periods=1).mean()

    # Source diversity
    daily['source_diversity'] = daily['source_ids'].apply(lambda x: len(set(x)) if x else 0)
    daily['source_mix_entropy'] = daily['source_ids'].apply(
        lambda x: -sum((c/len(x))*np.log2(c/len(x)) for c in Counter(x).values()) if x else 0
    )

    # Temporal features
    day_dt = pd.to_datetime(daily['day'])
    daily['weekend_flag'] = day_dt.dt.dayofweek.isin([5,6]).astype(int)
    daily['weekday'] = day_dt.dt.dayofweek
    daily['month'] = day_dt.dt.month

    # Days since last event
    ev = pd.read_sql_query("SELECT event_id, start_date FROM events ORDER BY start_date DESC LIMIT 1", conn)
    if not ev.empty:
        last_event = pd.Timestamp(ev['start_date'].iloc[0]).date()
        daily['days_since_event'] = (daily['day'].apply(lambda d: (d - last_event).days))
    else:
        daily['days_since_event'] = 999

    # Report lag (days between published and reported)
    if 'reported_at' in df.columns and df['reported_at'].notna().any():
        df['report_lag'] = (df['reported_at'] - df['published_at']).dt.total_seconds() / 86400
        report_lag_mean = df.groupby('day')['report_lag'].mean()
        report_lag_median = df.groupby('day')['report_lag'].median()
        daily['report_lag_days_mean'] = daily['day'].map(report_lag_mean).fillna(0)
        daily['report_lag_days_median'] = daily['day'].map(report_lag_median).fillna(0)
    else:
        daily['report_lag_days_mean'] = 0
        daily['report_lag_days_median'] = 0

    # Targets for supervised learning
    daily['next_day_incidents'] = daily['total_incidents'].shift(-1)
    daily['next_7_day_incidents'] = daily['total_incidents'].rolling(7, min_periods=1).sum().shift(-7)
    baseline = daily['rolling_7_incidents'].fillna(daily['total_incidents'].expanding().mean())
    daily['spike_label'] = (daily['total_incidents'] > baseline * 1.5).astype(int)

    # Fill remaining NaN
    num_cols = daily.select_dtypes(include=[np.number]).columns
    daily[num_cols] = daily[num_cols].fillna(0)

    return daily


def export_features(conn, path: str = 'features.csv') -> str:
    df = compute_features(conn)
    out_path = OUT_DIR / path
    df.to_csv(out_path, index=False)
    log.info(f"Features exported: {len(df)} rows to {out_path}")
    return str(out_path)


# ── Exports ────────────────────────────────────────────────────────
def export_csv(conn, path: str = 'incidents.csv', threshold: float = None) -> str:
    threshold = threshold or KEYWORD_THRESHOLD
    df = pd.read_sql_query("""
        SELECT i.incident_id, s.source_name as source, i.title, i.summary, i.incident_type,
               i.relevance_score, i.confidence, i.verified, i.online_flag, i.offline_flag,
               i.conflict_flag, i.protest_flag, i.far_right_flag
        FROM incidents i
        JOIN sources s ON i.source_id = s.source_id
        WHERE i.relevance_score >= ?
        ORDER BY i.relevance_score DESC
    """, conn, params=(threshold,))
    out_path = OUT_DIR / path
    df.to_csv(out_path, index=False)
    log.info(f"Exported {len(df)} incidents to {out_path}")
    return str(out_path)


def export_all(conn, path: str = 'all_items.csv') -> str:
    df = pd.read_sql_query("""
        SELECT i.incident_id, s.source_name as source, i.title, i.incident_type,
               i.relevance_score, i.confidence, i.verified, i.published_at,
               i.online_flag, i.offline_flag, i.conflict_flag, i.protest_flag, i.far_right_flag
        FROM incidents i
        JOIN sources s ON i.source_id = s.source_id
        ORDER BY i.relevance_score DESC
    """, conn)
    out_path = OUT_DIR / path
    df.to_csv(out_path, index=False)
    log.info(f"Exported {len(df)} items to {out_path}")
    return str(out_path)


# ── Alerts ─────────────────────────────────────────────────────────
ALERT_KEYWORDS = [
    'attack','stabbing','stabbed','fire','arson','vandalism','bomb',
    'threat','assault','killed','murder','cemetery',
    'lockdown','security','emergency','court','guilty','sentenced',
    'jailed','arrest','prosecution','cps','police investigate',
]

def get_alerts(conn, threshold: float = 0.5, limit: int = 15) -> List[Dict]:
    c = conn.cursor()
    c.execute("""
        SELECT s.source_name, i.title, i.relevance_score, i.incident_type, i.published_at
        FROM incidents i
        JOIN sources s ON i.source_id = s.source_id
        WHERE i.relevance_score >= ?
        ORDER BY i.relevance_score DESC, i.published_at DESC
        LIMIT ?
    """, (threshold, limit))
    rows = c.fetchall()
    return [{'source': r[0], 'title': r[1], 'relevance': r[2], 'type': r[3], 'published': r[4]} for r in rows]


def check_breaking(items: List[Dict]) -> List[Dict]:
    return [i for i in items if any(kw in (i['title'] or '').lower() for kw in ALERT_KEYWORDS)]


def log_pipeline_run(conn, run_start, run_end, fetched, new_items, avg_rel, status):
    c = conn.cursor()
    c.execute("INSERT INTO pipeline_runs VALUES (NULL,?,?,?,?,?,?)",
              (run_start, run_end, fetched, new_items, avg_rel, status))
    conn.commit()


# ── Main ───────────────────────────────────────────────────────────
def main(quick: bool = False) -> Dict:
    run_start = now_iso()
    log.info("=" * 60)
    log.info("Islamophobia Pipeline v3 — Full Schema")
    log.info(f"DB: {DB_PATH} | Quick: {quick}")
    log.info("=" * 60)

    conn = init_db()
    ensure_sources(conn)
    summary = {}

    try:
        fetched, new_incidents = ingest(conn, quick=quick)
        avg = pd.read_sql_query(
            "SELECT AVG(relevance_score) as a FROM incidents", conn
        )['a'].iloc[0] or 0.0
        metrics = build_daily_metrics(conn)
        csv_inc = export_csv(conn)
        csv_all = export_all(conn)
        feat_path = export_features(conn)

        summary = {
            'run_start': run_start, 'run_end': now_iso(),
            'items_fetched': fetched, 'new_items': new_incidents,
            'avg_relevance': round(float(avg), 3),
            'metrics': metrics,
            'exports': {'incidents_csv': csv_inc, 'all_csv': csv_all, 'features_csv': feat_path},
            'db': DB_PATH,
        }
        log_pipeline_run(conn, run_start, summary['run_end'], fetched, new_incidents, float(avg), 'success')

    except Exception as e:
        log.critical(f"Pipeline failed: {e}", exc_info=True)
        summary = {'run_start': run_start, 'run_end': now_iso(), 'status': 'failed', 'error': str(e)}
        log_pipeline_run(conn, run_start, summary['run_end'], 0, 0, 0.0, f'failed: {e}')

    with open(OUT_DIR / 'pipeline_summary.json', 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    conn.close()
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Islamophobia Pipeline v3')
    parser.add_argument('--quick', action='store_true', help='Ingest only, skip content')
    parser.add_argument('--features', action='store_true', help='Export feature vectors')
    parser.add_argument('--show-config', action='store_true', help='Show config')
    parser.add_argument('--alert', action='store_true', help='Show alerts')
    parser.add_argument('--db', type=str, default=DB_PATH)
    args = parser.parse_args()

    conn = init_db(args.db)
    ensure_sources(conn)

    if args.show_config:
        c = conn.cursor()
        c.execute("SELECT source_name, source_type, source_weight, active, last_fetched_at FROM sources")
        print("Active sources:")
        for r in c.fetchall():
            print(f"  {r[0]:30s} {str(r[1]):12s} weight={r[2]:.2f} active={'✅' if r[3] else '❌'} fetched={r[4] or 'never'}")
        conn.close()
        sys.exit(0)

    if args.features:
        df = export_features(conn)
        print(json.dumps({'features': df}, indent=2))
        conn.close()
        sys.exit(0)

    if args.alert:
        items = get_alerts(conn)
        breaking = check_breaking(items)
        print(f"\n🚨 Breaking: {len(breaking)} | Total alerts: {len(items)}\n")
        for item in items:
            tag = '🚨' if item in breaking else '  '
            print(f"{tag} [{item['relevance']:.2f}] {item['source']}: {item['title'][:90]}")
        conn.close()
        sys.exit(0)

    result = main(quick=args.quick)
    print(json.dumps(result, indent=2, default=str))
    conn.close()
