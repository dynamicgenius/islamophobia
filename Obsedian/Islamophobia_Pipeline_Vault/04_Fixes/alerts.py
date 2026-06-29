#!/usr/bin/env python3
"""
Islamophobia Pipeline — Alert Module (FIXED)
"""
import os, sys, json, sqlite3, subprocess
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime, timezone

DB_PATH = os.getenv("PIPELINE_DB", "output/islamophobia_v3.sqlite3")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "ibbiy@icloud.com")
BREAKING_THRESHOLD = 0.5

BREAKING_KEYWORDS = [
    "attack", "stabbing", "stabbed", "fire", "arson", "vandalism", "bomb",
    "threat", "assault", "killed", "murder", "death", "cemetery",
    "lockdown", "security", "emergency", "court", "guilty", "sentenced",
    "jailed", "arrest", "prosecution", "cps", "police investigate",
]

def load_alerts(threshold: float = BREAKING_THRESHOLD, limit: int = 15) -> List[Dict]:
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                s.source_name as source,
                i.title,
                s.url,
                i.relevance_score as relevance,
                i.published_at,
                i.fetched_at
            FROM incidents i
            JOIN sources s ON i.source_id = s.source_id
            WHERE i.relevance_score >= ?
            ORDER BY i.relevance_score DESC, i.published_at DESC
            LIMIT ?
        """, (threshold, limit))
        rows = cur.fetchall()
        conn.close()
        return [{"source": r[0], "title": r[1], "url": r[2], "relevance": r[3], "published_at": r[4] or r[5]} for r in rows]
    except sqlite3.OperationalError as e:
        print(f"⚠️ Database error: {e}")
        return []

def check_breaking(items: List[Dict]) -> List[Dict]:
    breaking = []
    for item in items:
        title_lower = (item.get("title") or "").lower()
        if any(kw in title_lower for kw in BREAKING_KEYWORDS):
            breaking.append(item)
    return breaking

def classify_severity(item: Dict) -> str:
    title = (item.get("title") or "").lower()
    score = item.get("relevance", 0)
    if score >= 0.8 and any(k in title for k in ["attack", "stab", "fire", "killed", "cemetery", "bomb"]):
        return "CRITICAL"
    elif score >= 0.7:
        return "HIGH"
    elif score >= 0.5:
        return "MEDIUM"
    return "LOW"

def send_email_alert(breaking: List[Dict]) -> Tuple[bool, str]:
    if not breaking:
        return True, "No breaking alerts to send"
    subject = f"Islamophobia BREAKING: {breaking[0]["title"][:60]}"
    body_lines = ["Islamophobia Pipeline — Breaking Alert", f"Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}", ""]
    for item in breaking[:5]:
        severity = classify_severity(item)
        body_lines.append(f"[{severity}] {item["source"]}")
        body_lines.append(f"  {item["title"]}")
        body_lines.append(f"  {item["url"]}")
        body_lines.append(f"  Relevance: {item["relevance"]:.2f}")
        body_lines.append("")
    body = "
".join(body_lines)
    msg = f"Subject: {subject}
To: {ALERT_EMAIL}
Content-Type: text/plain; charset=utf-8

{body}"
    try:
        proc = subprocess.run(["msmtp", ALERT_EMAIL], input=msg.encode("utf-8"), capture_output=True, timeout=15)
        if proc.returncode == 0:
            return True, f"Emailed {len(breaking)} breaking alerts to {ALERT_EMAIL}"
        return False, f"msmtp error: {proc.stderr.decode()[:200]}"
    except Exception as e:
        return False, f"Email failed: {e}"

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--breaking-only", action="store_true")
    parser.add_argument("--email", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--threshold", type=float, default=BREAKING_THRESHOLD)
    args = parser.parse_args()
    items = load_alerts(threshold=args.threshold)
    breaking = check_breaking(items)
    if args.json:
        print(json.dumps({"alerts": items, "breaking": breaking, "count": len(items), "breaking_count": len(breaking)}, indent=2))
        return
    if args.email and breaking:
        success, msg = send_email_alert(breaking)
        print(msg)
    if not items:
        print("No high-relevance items found.")
        return
    if args.breaking_only:
        if not breaking:
            print("No breaking stories detected.")
            return
        lines = ["🚨 **BREAKING ISLAMOPHOBIA ALERTS**
"]
        for item in breaking:
            severity = classify_severity(item)
            emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡"}.get(severity, "⚪")
            lines.append(f"{emoji} [{severity}] {item["title"][:100]}")
            lines.append(f"   Source: {item["source"]} | Score: {item["relevance"]:.2f}")
            lines.append(f"   {item["url"]}")
        print("
".join(lines))
        return
    lines = ["📋 **Islamophobia Pipeline — Alert Report**
"]
    if breaking:
        lines.append(f"🚨 Breaking stories: {len(breaking)}
")
    for item in items:
        severity = classify_severity(item)
        emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "⚪"}.get(severity, "⚪")
        is_breaking = "🚨" if item in breaking else ""
        lines.append(f"{emoji} {is_breaking} [{item["relevance"]:.2f}] {item["source"]}")
        lines.append(f"   {item["title"][:100]}")
        lines.append(f"   {item["url"]}")
    print("
".join(lines))

if __name__ == "__main__":
    main()
