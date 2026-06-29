#!/usr/bin/env python3
"""
Generate a proper multi-page simulation PDF report and email it.
Includes full prediction text, proper formatting, and layperson summary.
"""

import subprocess, os, json, sqlite3, sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from fpdf import FPDF

TO_EMAIL = "ibbiy@icloud.com"
FROM_EMAIL = "ibbiy@icloud.com"


class SimReportPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("DejaVu", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        self.add_font("DejaVu", "B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        self.add_font("DejaVu", "I", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

    def header(self):
        if self.page_no() > 1:
            self.set_font("DejaVu", "I", 6)
            self.set_text_color(150, 150, 150)
            self.cell(0, 5, "CyberAware UK | Islamophobia Trend Prediction", align="R", new_x="LMARGIN", new_y="NEXT")
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font("DejaVu", "I", 6)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}} | Confidential | CyberAware UK | cyberawareuk.co.uk", align="C")

    def section(self, title):
        self.set_font("DejaVu", "B", 11)
        self.set_text_color(26, 26, 46)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body_text(self, text):
        self.set_font("DejaVu", "", 8)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 4, text)
        self.ln(1)

    def bullet(self, text):
        self.set_font("DejaVu", "", 8)
        self.set_text_color(50, 50, 50)
        x0 = self.get_x()
        self.cell(5, 4, "\u2022")


def generate_simulation_pdf(prediction_text: str, date_str: str) -> str:
    out_path = f"/tmp/islamophobia_simulation_full_{datetime.now(timezone.utc).strftime('%d%m%y')}.pdf"

    pdf = SimReportPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    # Cover / Title block
    pdf.ln(10)
    pdf.set_font("DejaVu", "B", 18)
    pdf.set_text_color(24, 119, 242)
    pdf.cell(0, 12, "ISLAMOPHOBIA TREND PREDICTION", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, "UK Anti-Muslim Hate Landscape \u2014 48-Hour Forecast", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, date_str, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "Pipeline: MiroFish/DeepSeek Simulation | CyberAware UK", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_draw_color(24, 119, 242)
    pdf.set_line_width(0.5)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(6)

    # Layperson summary
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_text_color(220, 38, 38)
    pdf.cell(0, 6, "FOR DECISION MAKERS (Plain-English Summary)", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("DejaVu", "", 8.5)
    pdf.set_text_color(50, 50, 50)
    pdf.multi_cell(0, 4.2,
        "What this report tells you: This is a scenario-based forecast of how communities, media, "
        "and policymakers are likely to react to recent anti-Muslim hate incidents across the UK. "
        "It is not a count of incidents \u2014 that is in the separate ML Prediction Report. "
        "The simulation identifies the most likely flashpoints, who will react and how, and where the "
        "biggest risks of escalation lie. Use this to prepare communications, engage stakeholders, "
        "and allocate resources ahead of developing events."
    )
    pdf.ln(4)

    # Disclaimer box
    pdf.set_fill_color(255, 243, 224)
    pdf.set_draw_color(249, 201, 36)
    y0 = pdf.get_y()
    pdf.rect(15, y0, 180, 14, style="DF")
    pdf.set_xy(18, y0 + 1)
    pdf.set_font("DejaVu", "I", 7)
    pdf.set_text_color(150, 100, 0)
    pdf.multi_cell(174, 3.5,
        "Disclaimer: This report is an exploratory trend prediction based on news clustering and "
        "multi-agent simulation. It is not a guaranteed forecast. Treat as early warning intelligence "
        "for monitoring and preparedness."
    )
    pdf.ln(6)

    # Parse prediction text into sections
    lines = prediction_text.strip().split("\n")
    current_section = None
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Detect headings
        is_heading = False
        if line_stripped.startswith("###") or line_stripped.startswith("##"):
            is_heading = True
            clean = line_stripped.lstrip("#").strip()
        elif line_stripped.isupper() and len(line_stripped) > 3 and line_stripped[0].isalpha():
            is_heading = True
            clean = line_stripped

        if is_heading:
            pdf.ln(2)
            pdf.section(clean)
            continue

        # Bullet or body
        if line_stripped.startswith("- ") or line_stripped.startswith("* "):
            pdf.body_text("  \u2022  " + line_stripped[2:])
        else:
            # Bold text marked with **...**
            if "**" in line_stripped:
                parts = line_stripped.split("**")
                pdf.set_font("DejaVu", "B", 8)
                pdf.set_text_color(50, 50, 50)
                for i, part in enumerate(parts):
                    if i % 2 == 1:
                        pdf.set_font("DejaVu", "B", 8)
                    else:
                        pdf.set_font("DejaVu", "", 8)
                    pdf.write(4, part + " ")
                pdf.ln(4)
            else:
                pdf.body_text(line_stripped)

    # Branding footer
    pdf.ln(6)
    pdf.set_draw_color(249, 201, 36)
    pdf.set_line_width(0.5)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("DejaVu", "B", 9)
    pdf.set_text_color(249, 201, 36)
    pdf.cell(0, 5, "WE FEAR NO ONE", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 7)
    pdf.set_text_color(24, 119, 242)
    pdf.cell(0, 5, "GUARDED BY BULLY \u2014 DIGITAL THREAT RESPONSE UNIT", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 6)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 4, "https://cyberawareuk.co.uk", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.output(out_path)
    return out_path


def send_pdf(pdf_path: str, subject: str, body: str):
    msg = MIMEMultipart()
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    with open(pdf_path, "rb") as f:
        pdf_data = f.read()
    part = MIMEBase("application", "pdf")
    part.set_payload(pdf_data)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=os.path.basename(pdf_path))
    msg.attach(part)
    proc = subprocess.Popen(["msmtp", "--read-envelope-from", "-t"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.communicate(msg.as_bytes())
    return proc.returncode == 0


if __name__ == "__main__":
    # Get latest simulation from structured pipeline DB
    conn = sqlite3.connect("/root/.openclaw/workspace/projects/islamophobia_pipeline/data/pipeline.db")
    cur = conn.cursor()
    # Get the most complete simulation (longest report text)
    cur.execute("SELECT report, created_at FROM simulations ORDER BY LENGTH(report) DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()

    if not row:
        print("No simulations found")
        sys.exit(1)

    report = json.loads(row[0])
    text = report.get("prediction", "No prediction available")
    created = row[1]
    date_str = datetime.fromisoformat(created).strftime("%d %B %Y, %H:%M UTC")

    print(f"Generating simulation PDF ({len(text)} chars)...")
    pdf_path = generate_simulation_pdf(text, date_str)
    size = os.path.getsize(pdf_path)
    print(f"PDF generated: {size} bytes ({size//1024}KB)")

    subject = f"ISLAMOPHOBIA TREND PREDICTION — Full Simulation Report — {datetime.now(timezone.utc).strftime('%d %B %Y')}"
    body = f"""Hi Ibby,

Here is the full Islamophobia simulation report with scenario analysis.

Report date: {date_str}
Analysis length: Full multi-section forecast

This is the "big report" format — covers early backlash signals, narrative compression, influencer framing, coalition formation, and policy reactions across the UK landscape.

📎 Full PDF attached.

⚔️ WE FEAR NO ONE
🐾 GUARDED BY BULLY — DIGITAL THREAT RESPONSE UNIT
"""

    if send_pdf(pdf_path, subject, body):
        print(f"✅ Simulation report ({size//1024}KB) emailed to {TO_EMAIL}")
    else:
        print("❌ Email failed")
