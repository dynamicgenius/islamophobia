"""
Islamophobia Pipeline — Runner
Orchestrates source ingestion using db_utils for all DB operations.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from db_utils import (
    ensure_schema, upsert_source, upsert_incident, tag_incident,
    refresh_daily_metrics, now_iso, relevance_score, make_id,
)

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

from bs4 import BeautifulSoup
import requests
import pandas as pd

log = logging.getLogger(__name__)

# ── Source definitions ──
# (name, type, url, weight)
SOURCES = [
    ('TellMAMA',            'advocacy', 'https://tellmamauk.org',                                                                  0.9),
    ('IRU',                 'advocacy', 'https://www.theiru.org.uk',                                                               0.85),
    ('BBC_RSS_UK',          'news',     'https://feeds.bbci.co.uk/news/uk/rss.xml',                                                0.4),
    ('BBC_RSS_World',       'news',     'https://feeds.bbci.co.uk/news/world/rss.xml',                                             0.4),
    ('Guardian_RSS',        'news',     'https://www.theguardian.com/uk/rss',                                                      0.4),
    ('Guardian_Society',    'news',     'https://www.theguardian.com/society/rss',                                                 0.4),
    ('Guardian_Religion',   'news',     'https://www.theguardian.com/world/religion/rss',                                          0.4),
    ('SkyNews_RSS',         'news',     'https://feeds.skynews.com/feeds/rss/uk.xml',                                              0.4),
    ('SkyNews_RSS_Home',    'news',     'https://feeds.skynews.com/feeds/rss/home.xml',                                            0.4),
    ('Independent_RSS',     'news',     'https://www.independent.co.uk/rss',                                                       0.4),
    ('Independent_Voices',  'news',     'https://www.independent.co.uk/voices/rss',                                               0.4),
    ('iNews_RSS',           'news',     'https://inews.co.uk/feed',                                                               0.4),
    ('DailyMail_RSS',       'news',     'https://www.dailymail.co.uk/articles.rss',                                               0.4),
    ('DailyMail_News',      'news',     'https://www.dailymail.co.uk/news/index.rss',                                             0.4),
    ('Telegraph_News',      'news',     'https://www.telegraph.co.uk/news/rss.xml',                                               0.4),
    ('AJ_UK_RSS',           'news',     'https://www.aljazeera.com/xml/rss/all.xml',                                               0.4),
    ('GoogleNews_Islamophobia', 'news', 'https://news.google.com/rss/search?q=islamophobia+UK&hl=en-GB&gl=GB&ceid=GB:en',          0.4),
    ('GoogleNews_AntiMuslim',   'news', 'https://news.google.com/rss/search?q=%22anti-Muslim%22+hate+crime+UK&hl=en-GB&gl=GB&ceid=GB:en', 0.4),
    ('GoogleNews_HateCrime',    'news', 'https://news.google.com/rss/search?q=%22hate+crime%22+muslim+UK&hl=en-GB&gl=GB&ceid=GB:en', 0.4),
    ('GoogleNews_MosqueAttack', 'news', 'https://news.google.com/rss/search?q=mosque+attack+vandalism+UK&hl=en-GB&gl=GB&ceid=GB:en', 0.4),
]

MAX_ARTICLES_PER_SOURCE = 25

# ── Flag helpers ──
FLAG_KEYWORDS = {
    'protest': ['protest','march','rally','demonstration'],
    'conflict': ['gaza','israel','palestine','hamas','hezbollah'],
    'far_right': ['far-right','far right','edl','britain first','patriotic alternative','national front'],
    'online': ['online','social media','twitter','tiktok','telegram','instagram','facebook'],
    'offline': ['assault','attack','vandalism','threat','abuse','stab','arson','mosque'],
}

INCIDENT_TYPES = {
    'assault': ['assault','attack','stab','beaten','punched','kicked'],
    'abuse': ['abuse','racial abuse','religious abuse','verbal abuse'],
    'vandalism': ['vandalism','graffiti','damage','smashed'],
    'threat': ['threat','intimidation','harassment','menaced'],
    'discrimination': ['discrimination','bias','profiling','exclusion'],
}


def classify_flags(text: str) -> Dict[str, int]:
    t = (text or '').lower()
    return {
        'protest_flag': int(any(k in t for k in FLAG_KEYWORDS['protest'])),
        'conflict_flag': int(any(k in t for k in FLAG_KEYWORDS['conflict'])),
        'far_right_flag': int(any(k in t for k in FLAG_KEYWORDS['far_right'])),
        'online_flag': int(any(k in t for k in FLAG_KEYWORDS['online'])),
        'offline_flag': int(any(k in t for k in FLAG_KEYWORDS['offline'])),
    }


def classify_incident_type(text: str) -> str:
    t = (text or '').lower()
    best_type = 'discrimination'
    best_score = 0
    for itype, patterns in INCIDENT_TYPES.items():
        score = sum(1 for p in patterns if p in t)
        if score > best_score:
            best_score = score
            best_type = itype
    return best_type


# ── Fetching ──
def fetch_url(url: str, timeout: int = 20) -> str:
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; IslamophobiaPipeline/3.0)'}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.warning(f"Fetch failed: {url[:80]} — {e}")
        raise


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script','style','noscript']):
        tag.decompose()
    return ' '.join(soup.get_text(' ', strip=True).split())


# ── RSS parsing ──
def parse_rss(source_name: str, url: str) -> List[Dict]:
    """Parse RSS feed, return list of incident-like dicts."""
    items = []
    if HAS_FEEDPARSER:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
                link = entry.get('link', '')
                if not link:
                    continue
                title = entry.get('title', 'Untitled')
                summary = entry.get('summary', '') or ''
                published = entry.get('published') or entry.get('updated')
                text = f'{title} {summary} {source_name}'
                flags = classify_flags(text)
                itype = classify_incident_type(text)
                items.append({
                    'title': ' '.join(title.split()),
                    'summary': ' '.join(summary.split()),
                    'published_at': published,
                    'incident_type': itype,
                    'confidence': relevance_score(text),
                    'link': link,  # ← ADDED: store the article URL
                    **flags,
                })
            log.info(f"  [RSS] {source_name}: {len(items)} articles")
            return items
        except Exception as e:
            log.warning(f"  [RSS] feedparser failed {source_name}: {e}")

    # Fallback BS4
    try:
        xml = fetch_url(url)
        soup = BeautifulSoup(xml, 'xml')
        entries = soup.find_all('item') or soup.find_all('entry')
        for entry in entries[:MAX_ARTICLES_PER_SOURCE]:
            link_tag = entry.find('link')
            if not link_tag:
                continue
            link = link_tag.get('href', '') or link_tag.get_text(strip=True)
            if not link:
                continue
            title = entry.find('title')
            title = title.get_text(strip=True) if title else 'Untitled'
            text = f'{title} {source_name}'
            flags = classify_flags(text)
            items.append({
                'title': title,
                'summary': '',
                'published_at': None,
                'incident_type': classify_incident_type(text),
                'confidence': relevance_score(text),
                'link': link,  # ← ADDED: store the article URL
                **flags,
            })
        log.info(f"  [RSS] {source_name}: {len(items)} (BS4)")
    except Exception as e:
        log.error(f"  [RSS] {source_name}: failed: {e}")
    return items


# ── HTML parsing ──
def parse_html(source_name: str, url: str) -> List[Dict]:
    """Fetch and parse a single HTML page as one incident."""
    try:
        html = fetch_url(url)
        text = extract_text(html)
        title = ''
        soup = BeautifulSoup(html, 'html.parser')
        if soup.title:
            title = ' '.join(soup.title.get_text(strip=True).split())
        combined = f'{title} {text[:2000]} {source_name}'
        flags = classify_flags(combined)
        itype = classify_incident_type(combined)
        return [{
            'title': title or source_name,
            'summary': text[:500],
            'content': text,
            'incident_type': itype,
            'confidence': relevance_score(combined),
            'link': url,  # ← ADDED: store the URL
            **flags,
        }]
    except Exception as e:
        log.warning(f"  [HTML] {source_name}: {e}")
        return []


# ── Ingest ──
def ingest_sources(conn, quick: bool = False) -> Tuple[int, int]:
    """
    Ingest all active sources into the DB.
    Returns (total_fetched, new_count).
    """
    total = 0
    new = 0

    for name, stype, url, weight in SOURCES:
        try:
            # Upsert source definition
            sid = upsert_source(conn, name, stype, url, weight=weight)

            # Fetch items
            if stype in ('news', 'rss'):
                items = parse_rss(name, url)
            else:
                items = parse_html(name, url)

            # Upsert each incident
            for item in items:
                iid, score = upsert_incident(
                    conn=conn,
                    source_id=sid,
                    title=item.get('title', 'Untitled'),
                    summary=item.get('summary', ''),
                    content=item.get('content', item.get('summary', '')),
                    incident_type=item.get('incident_type', 'discrimination'),
                    published_at=item.get('published_at'),
                    confidence=item.get('confidence', 0),
                    event_flag=item.get('event_flag', 0),
                    conflict_flag=item.get('conflict_flag', 0),
                    protest_flag=item.get('protest_flag', 0),
                    far_right_flag=item.get('far_right_flag', 0),
                    offline_flag=item.get('offline_flag', 0),
                    online_flag=item.get('online_flag', 0),
                    article_url=item.get('link', ''),  # ← ADDED: store article URL
                )
                total += 1

                # Check if it's new (compare against existing count or use a simple heuristic)
                # For now, track via threshold — new items have unique incident_id
            new += len(items)  # approximate; real dedup happens in upsert_incident's ON CONFLICT

            # Update last_fetched_at
            conn.execute("UPDATE sources SET last_fetched_at=? WHERE source_id=?",
                         (now_iso(), sid))
            conn.commit()

        except Exception as e:
            log.error(f"[{name}] Ingest error: {e}")

    return total, new


# ── Full run ──
def bootstrap(db_path: str = None) -> tuple:
    """Bootstrap: ensure schema, upsert all sources. Returns (conn, ids_dict)."""
    db_path = db_path or 'output/islamophobia_v3.sqlite3'
    conn = ensure_schema(db_path)
    ids = {}
    for name, stype, url, weight in SOURCES:
        ids[name] = upsert_source(conn, name, stype, url, weight=weight)
    return conn, ids


def seed_examples(conn, ids):
    """Seed with example incidents for testing (from pipeline_runner original)."""
    # from alerts import prediction_alert_main  # no-op import for side effects
    seeded = []
    examples = [
        (ids.get('home_office') or ids.get('TellMAMA'), 'Home Office hate crime bulletin',
         'Official E&W hate crime stats', 'Muslim-targeted religious hate crime rose.',
         'official', 1, '2025-10-09', 0.95, {'offline_flag': 1}),
        (ids.get('tell_mama') or ids.get('IRU'), 'Tell MAMA report',
         '2024 anti-Muslim hate cases', '6,313 reports in 2024',
         'community', 1, '2025-02-19', 0.9, {'online_flag': 1, 'event_flag': 1}),
    ]
    for sid, title, summary, content, itype, verified, pub, conf, flags in examples:
        if sid:
            iid, _ = upsert_incident(conn, sid, title, summary, content,
                                      incident_type=itype, verified=verified,
                                      published_at=pub, confidence=conf, **flags)
            seeded.append(iid)
    conn.commit()
    return seeded


def run(db_path: str = None, quick: bool = False) -> Dict:
    """Full pipeline run. Returns summary dict."""
    import time
    run_start = now_iso()
    db_path = db_path or 'output/islamophobia_v3.sqlite3'
    log.info("=" * 60)
    log.info(f"Pipeline v3 — DB: {db_path}")
    log.info("=" * 60)

    conn = ensure_schema(db_path)
    fetched, new = ingest_sources(conn, quick=quick)
    daily = refresh_daily_metrics(conn)

    # Deduplicate incidents before feature building
    try:
        from dedup import dedup_incidents_db
        deduped, audit = dedup_incidents_db(db_path)
        dupes_removed = len(audit)
        kept = len(deduped)
        log.info(f"Dedup: {dupes_removed} duplicates merged, {kept} unique records kept")
    except Exception as dedup_e:
        log.warning(f"Dedup skipped: {dedup_e}")
        dupes_removed = 0

    # Build daily features for ML
    try:
        from daily_features import build_daily_features
        df_incidents = pd.read_sql_query('SELECT * FROM incidents', conn)
        feats = build_daily_features(df_incidents)
        feat_path = str(Path(db_path).parent / 'features_daily.csv') if Path(db_path).parent else 'output/features_daily.csv'
        feats.to_csv(feat_path, index=False)
        log.info(f"Features exported: {len(feats)} rows to {feat_path}")
    except Exception as e:
        log.warning(f"Features skipped: {e}")
        feat_path = None

    # Train model + predict if enough data
    if feat_path:
        try:
            # Load features and reformat for Poisson/HGBR models
            feat_df = pd.read_csv(feat_path)
            train_df = feat_df.rename(columns={'day': 'date', 'incidents': 'incident_count'}).copy()
            train_df['date'] = pd.to_datetime(train_df['date'])
            train_df = train_df.sort_values('date').reset_index(drop=True)
            train_csv = feat_path.replace('.csv', '_train.csv')
            train_df[['date', 'incident_count']].to_csv(train_csv, index=False)
            log.info(f"Training data: {len(train_df)} rows, {train_df['incident_count'].sum():.0f} total incidents")

            from train import run_pipeline
            metrics, forecast_df, best_model, best_forecast = run_pipeline(train_csv, output_dir=Path(feat_path).parent)
            log.info(f"Models trained: {metrics['mae'].iloc[0]:.3f}/{metrics['rmse'].iloc[0]:.3f} MAE/RMSE (Poisson), {metrics['mae'].iloc[1]:.3f}/{metrics['rmse'].iloc[1]:.3f} MAE/RMSE (HGBR)")
            log.info(f"Best: {best_model} — forecast: {best_forecast['forecast']} (CI: {best_forecast['forecast_lower']}-{best_forecast['forecast_upper']})")

            pred_val = float(best_forecast['forecast'])
            pred_csv = Path(feat_path).parent / 'next_day_forecast.csv'

            # Write legacy predictions.csv for alerts.py compatibility
            leg_path = str(Path(feat_path).parent / 'predictions.csv')
            leg_df = pd.DataFrame({'horizon': ['next_day'], 'prediction': [pred_val]})
            leg_df.to_csv(leg_path, index=False)

            # Generate prediction alerts
            try:
                # from alerts import prediction_alert_main
                # alert_result = prediction_alert_main(pred_path=leg_path)
                if alert_result.get('alerts', 0) > 0:
                    log.warning(f"🚨 {alert_result['alerts']} prediction alert(s) generated (prediction: {pred_val:.0f})")
                    
                    # Generate PDF report and email it
                    try:
                        import subprocess as sh_mod
                        # Get top headlines for the report
                        head_result = sh_mod.run([
                            'sqlite3', db_path or 'output/islamophobia_v3.sqlite3',
                            '-json',
                            'SELECT s.source_name, i.title, i.relevance_score FROM incidents i JOIN sources s ON i.source_id=s.source_id WHERE i.relevance_score >= 0.3 ORDER BY i.relevance_score DESC LIMIT 10'
                        ], capture_output=True, timeout=10, cwd=Path(db_path).parent or '.')
                        headlines_json = head_result.stdout.decode() if head_result.returncode == 0 else '[]'
                        # Quick count from DB for email report
                        c_count = conn.cursor()
                        c_count.execute("SELECT COUNT(*), AVG(relevance_score) FROM incidents")
                        total_inc, avg_rel_val = c_count.fetchone()
                        total_inc = total_inc or 0
                        avg_rel_val = round(avg_rel_val or 0.0, 3)
                        
                        cmd = [
                            'python3',
                            str(Path(__file__).parent / 'send_prediction_email.py'),
                            '--prediction', str(pred_val),
                            '--items', str(fetched),
                            '--incidents', str(total_inc),
                            '--relevance', str(avg_rel_val),
                            '--mae', str(metrics['mae'].min()),
                            '--rmse', str(metrics['rmse'].min()),
                            '--headlines', headlines_json,
                        ]
                        sh_mod.run(cmd, capture_output=True, timeout=30)
                        log.info(f'📧 PDF report emailed to ibbiy@icloud.com (prediction: {pred_val:.0f})')
                    except Exception as pdf_e:
                        log.warning(f'PDF/email skipped: {pdf_e}')
            except Exception as alert_e:
                log.warning(f"Prediction alerts skipped: {alert_e}")
        except Exception as e:
            log.warning(f"Model training skipped: {e}")

    # Stats
    c = conn.cursor()
    c.execute("SELECT COUNT(*), AVG(relevance_score) FROM incidents")
    total_incidents, avg_rel = c.fetchone()
    avg_rel = round(avg_rel or 0.0, 3)

    summary = {
        'run_start': run_start,
        'run_end': now_iso(),
        'items_fetched': fetched,
        'new_items': new,
        'total_in_db': total_incidents,
        'avg_relevance': avg_rel,
        'daily_rows': 0 if daily is None else len(daily),
        'features_csv': feat_path,
    }
    log.info(json.dumps(summary, indent=2))
    conn.close()
    return summary


if __name__ == '__main__':
    import json
    import sys
    print(json.dumps(run(db_path=sys.argv[1] if len(sys.argv) > 1 else None), indent=2))
