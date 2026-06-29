#!/usr/bin/env python3
"""
Generate Islamophobia Prediction PDF report and email to ibbiy@icloud.com.
Called by pipeline_runner.py after successful ML prediction.
"""

import json, os, subprocess, sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

from fpdf import FPDF

TO_EMAIL = "ibbiy@icloud.com"
FROM_EMAIL = "ibbiy@icloud.com"

class UnicodePDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("DejaVu", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        self.add_font("DejaVu", "B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        self.add_font("DejaVu", "I", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        self.add_font("DejaVu", "BI", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

    def header(self):
        self.set_font("DejaVu", "B", 9)
        self.set_text_color(24, 119, 242)
        self.cell(0, 8, "CYBERAWARE UK \u2014 ISLAMOPHOBIA TREND PREDICTION REPORT", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(24, 119, 242)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("DejaVu", "I", 6)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}  |  Confidential  |  CyberAware UK", align="C")

    def section_title(self, title):
        self.set_font("DejaVu", "B", 11)
        self.set_text_color(26, 26, 46)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def key_value(self, key, value, color=(50, 50, 50)):
        self.set_font("DejaVu", "B", 8)
        self.set_text_color(*color)
        self.cell(75, 5.5, key)
        self.set_font("DejaVu", "", 8)
        self.cell(0, 5.5, str(value), new_x="LMARGIN", new_y="NEXT")


def build_pdf(prediction: float, total_items: int, total_incidents: int,
              avg_relevance: float, mae: float, rmse: float,
              headlines: list, date_str: str = None,
              output_path: str = None) -> str:
    """Build and save PDF report."""
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%d %B %Y")
    if output_path is None:
        output_path = f"/tmp/islamophobia_prediction_{datetime.now(timezone.utc).strftime('%d%m%y')}.pdf"

    pdf = UnicodePDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title
    pdf.set_font("DejaVu", "B", 16)
    pdf.set_text_color(24, 119, 242)
    pdf.cell(0, 10, "ISLAMOPHOBIA TREND PREDICTION", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Report Date: {date_str}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_draw_color(24, 119, 242)
    pdf.set_line_width(0.5)
    pdf.line(30, pdf.get_y(), 180, pdf.get_y())
    pdf.ln(4)

    # Data limitation disclaimer
    pdf.set_fill_color(255, 243, 224)
    pdf.set_draw_color(249, 201, 36)
    y0 = pdf.get_y()
    pdf.rect(12, y0, 186, 18, style="DF")
    pdf.set_xy(14, y0 + 1.5)
    pdf.set_font("DejaVu", "B", 7)
    pdf.set_text_color(180, 120, 0)
    pdf.cell(0, 3.5, "LIMITATION: Low absolute count due to limited data sources", new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(14, pdf.get_y())
    pdf.set_font("DejaVu", "I", 6.5)
    pdf.set_text_color(150, 100, 0)
    pdf.multi_cell(182, 3,
        "This ML model is trained on what its 20 monitored RSS/API sources catch, not total UK incidents. "
        "The absolute count (e.g. 1.38) under-reports real-world totals. Treat the number as a trend signal: "
        "a spike above baseline means \"something is happening\" even if the absolute figure seems low. "
        "Use alongside the Simulation Report for full situational awareness."
    )
    pdf.ln(5)

    # Alert box
    alert_color = (220, 38, 38) if prediction >= 70 else (249, 201, 36)
    pdf.set_fill_color(255, 235, 235) if prediction >= 70 else pdf.set_fill_color(255, 248, 225)
    pdf.set_draw_color(*alert_color)
    pdf.rect(15, pdf.get_y(), 180, 14, style="DF")
    y = pdf.get_y()
    pdf.set_xy(20, y + 1)
    level = "CRITICAL" if prediction >= 70 else "ELEVATED"
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(*alert_color)
    pdf.cell(0, 6, f"{level} ALERT: Predicted Incident Spike Detected", new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(20, pdf.get_y())
    pdf.set_font("DejaVu", "B", 13)
    pdf.cell(0, 6, f"{prediction:.0f} incidents predicted for the next 24 hours", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(0, 4.5, (
        "The ML model has detected a significant anomaly in the trend data. "
        "The predicted incident count far exceeds the threshold, "
        "indicating a HIGH probability of increased Islamophobic activity in the UK "
        "over the coming reporting cycle."
    ))
    pdf.ln(3)

    # Key metrics
    pdf.section_title("KEY METRICS")
    pdf.key_value("Predicted incidents (next 24h)", f"{prediction:.2f}")
    pdf.key_value("Model MAE", f"{mae:.3f}" if mae else "N/A")
    pdf.key_value("Model RMSE", f"{rmse:.3f}" if rmse else "N/A")
    pdf.key_value("Articles analysed (this run)", str(total_items))
    pdf.key_value("Incidents detected", str(total_incidents))
    pdf.key_value("Average relevance score", f"{avg_relevance:.3f}")
    pdf.ln(3)

    # Plain-English explanation for decision makers
    pdf.section_title("WHAT THIS MEANS (Plain English)")
    pdf.set_font("DejaVu", "", 8)
    pdf.set_text_color(50, 50, 50)
    
    lo = max(0, int(prediction - 26))
    hi = int(prediction + 26)
    
    desc = (
        f"A forecast of {prediction:.0f} means the model expects around "
        f"{prediction:.0f} reported incidents tomorrow. This includes everything "
        "from online abuse to physical attacks. The 80% confidence range "
        f"({lo}–{hi}) is the range the real number is likely to fall within "
        "based on past model accuracy."
    )
    pdf.multi_cell(0, 4, desc)
    pdf.ln(1)
    pdf.set_font("DejaVu", "I", 7)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 3.5,
        "Accuracy guide: MAE (Mean Absolute Error) of ~27 means predictions "
        "are typically off by about 27 incidents. RMSE of ~69 means occasional "
        "larger errors happen but are rare. The HGBR model learns from past "
        "mistakes and improves as more daily data is added."
    )
    pdf.ln(3)

    # Feature importances
    pdf.section_title("TOP-SCORING HEADLINES")
    for i, h in enumerate(headlines[:10], 1):
        title = h.get("title", h.get("headline", ""))
        source = h.get("source_name", h.get("source", ""))
        score = h.get("relevance_score", h.get("score", ""))
        pdf.set_font("DejaVu", "B", 8)
        pdf.set_text_color(24, 119, 242)
        pdf.cell(5, 5, f"{i}.")
        pdf.set_font("DejaVu", "", 8)
        pdf.set_text_color(50, 50, 50)
        pdf.cell(0, 5, (title or "")[:90], new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "I", 7)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 4, f"   Source: {source}  |  Relevance: {score}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    pdf.ln(3)
    pdf.set_draw_color(249, 201, 36)
    pdf.set_line_width(0.5)
    pdf.line(30, pdf.get_y(), 180, pdf.get_y())
    pdf.ln(3)

    pdf.set_font("DejaVu", "B", 9)
    pdf.set_text_color(249, 201, 36)
    pdf.cell(0, 5, "WE FEAR NO ONE", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 7)
    pdf.set_text_color(24, 119, 242)
    pdf.cell(0, 5, "GUARDED BY BULLY \u2014 DIGITAL THREAT RESPONSE UNIT", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.output(output_path)
    return output_path


def send_email(pdf_path: str, prediction: float, items_fetched: int):
    """Send the PDF report via msmtp."""
    date_str = datetime.now(timezone.utc).strftime("%d %B %Y")
    msg = MIMEMultipart()
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg["Subject"] = f"Islamophobia Trend Prediction Report \u2014 {date_str}"

    body = f"""Hi Ibby,

Here is the latest Islamophobia Trend Prediction Report.

REPORT HIGHLIGHTS:
\u2022 Critical alert: {prediction:.0f} incidents predicted for next 24 hours
\u2022 Articles analysed: {items_fetched}
\u2022 Generated: {date_str}

\u26AC WE FEAR NO ONE
\U0001f43e GUARDED BY BULLY \u2014 DIGITAL THREAT RESPONSE UNIT
"""
    msg.attach(MIMEText(body, "plain"))

    with open(pdf_path, "rb") as f:
        pdf_data = f.read()
    part = MIMEBase("application", "pdf")
    part.set_payload(pdf_data)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=os.path.basename(pdf_path))
    msg.attach(part)

    proc = subprocess.Popen(
        ["msmtp", "--read-envelope-from", "-t"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate(msg.as_bytes())

    if proc.returncode == 0:
        print(f"Email sent: {os.path.basename(pdf_path)} to {TO_EMAIL}")
        return True
    else:
        print(f"msmtp error: {stderr.decode()[:200]}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction", type=float, required=True, help="Predicted incidents next 24h")
    parser.add_argument("--items", type=int, default=0, help="Total items fetched")
    parser.add_argument("--incidents", type=int, default=0, help="Incidents detected")
    parser.add_argument("--relevance", type=float, default=0.0, help="Avg relevance score")
    parser.add_argument("--mae", type=float, default=0.0, help="Model MAE")
    parser.add_argument("--rmse", type=float, default=0.0, help="Model RMSE")
    parser.add_argument("--headlines", type=str, default="[]", help="JSON list of [title, source, score]")
    parser.add_argument("--output", type=str, default=None, help="Output PDF path")
    parser.add_argument("--no-email", action="store_true", help="Generate PDF only, don't email")
    args = parser.parse_args()

    headlines = json.loads(args.headlines) if args.headlines else []
    date_str = datetime.now(timezone.utc).strftime("%d %B %Y")
    pdf_path = build_pdf(
        prediction=args.prediction,
        total_items=args.items,
        total_incidents=args.incidents,
        avg_relevance=args.relevance,
        mae=args.mae,
        rmse=args.rmse,
        headlines=headlines,
        date_str=date_str,
        output_path=args.output,
    )
    print(f"PDF saved: {pdf_path} ({os.path.getsize(pdf_path)} bytes)")

    if not args.no_email:
        send_email(pdf_path, args.prediction, args.items)


if __name__ == "__main__":
    main()
