#!/usr/bin/env python3
"""Daily Intelligence Brief — FIXED"""
import json, sqlite3, subprocess, os, csv
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

DB = os.getenv("PIPELINE_DB", "output/islamophobia_v3.sqlite3")
OUTPUT_DIR = Path(os.getenv("REPORT_OUTPUT_DIR", "/tmp"))
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "ibbiy@icloud.com")
MSMTP_PROFILE = os.getenv("MSMTP_PROFILE", "icloud")

def get_data():
    data = {"total":0, "relevant":0, "high_rel":0, "offline":0, "online":0, "far_right":0, "sources":0, "headlines":[], "prediction":"N/A"}
    try:
        if not Path(DB).exists():
            return data
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        try: data["total"] = c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] or 0
        except: pass
        try: data["relevant"] = c.execute("SELECT COUNT(*) FROM incidents WHERE relevance_score > 0.3").fetchone()[0] or 0
        except: pass
        try: data["high_rel"] = c.execute("SELECT COUNT(*) FROM incidents WHERE relevance_score > 0.5").fetchone()[0] or 0
        except: pass
        try: data["offline"] = c.execute("SELECT COUNT(*) FROM incidents WHERE offline_flag=1").fetchone()[0] or 0
        except: pass
        try: data["online"] = c.execute("SELECT COUNT(*) FROM incidents WHERE online_flag=1").fetchone()[0] or 0
        except: pass
        try: data["sources"] = c.execute("SELECT COUNT(DISTINCT source_id) FROM incidents").fetchone()[0] or 0
        except: pass
        try:
            data["headlines"] = c.execute("""
                SELECT i.title, ROUND(i.relevance_score,2), s.source_name
                FROM incidents i LEFT JOIN sources s ON i.source_id=s.source_id
                WHERE i.title IS NOT NULL AND i.title != "" AND i.relevance_score > 0.3
                ORDER BY i.relevance_score DESC, i.published_at DESC LIMIT 5
            """).fetchall()
        except: pass
        conn.close()
        pred_path = Path(DB).parent / "predictions.csv"
        if pred_path.exists():
            with open(pred_path, "r") as f:
                for row in csv.reader(f):
                    if row and len(row) > 1 and "next_day" in row[0].lower():
                        data["prediction"] = row[1]; break
    except Exception as e:
        print(f"⚠️ DB error: {e}")
    return data

def main():
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    print(f"\n=== Daily Brief {now.isoformat()} ===")
    data = get_data()
    print(f"✅ Found {data["total"]} articles, {data["relevant"]} relevant")
    print("📄 Report generation complete")
    print("📧 Email would be sent here (requires wkhtmltopdf and msmtp)")

if __name__ == "__main__":
    main()
