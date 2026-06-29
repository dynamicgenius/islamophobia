# Daily Intelligence Brief — How the Data Is Generated

## A Plain-English Explanation for the Panel

---

### What This Is

Every morning at 8am, a single-page intelligence report lands in my inbox. It monitors anti-Muslim hate and Islamophobia across the UK by reading 20 different news sources around the clock — mainstream media (BBC, Guardian, Daily Mail, etc.), specialist monitoring organisations (Tell MAMA, Islamophobia Response Unit), and Google News keyword alerts — and flagging every article that relates to anti-Muslim hate, discrimination, or Islamophobia.

---

### How It Works

**Step 1: Collection (24/7)**
An automated pipeline runs every 30 minutes to two hours, pulling in articles from all 20 sources using RSS feeds, APIs, and web scraping. It does not stop. It has been running continuously for several months.

**Step 2: Classification**
Every article is analysed and tagged by type:
- **Discrimination** — reports, legal cases, policy debates (88% of what we see)
- **Assault or physical attacks** — actual violent incidents (8%)
- **Threats or intimidation** (2%)
- **Vandalism or property damage** (1%)
- **Verbal abuse or harassment** (under 1%)

**Step 3: Relevance Scoring**
Each article is scored on how relevant it is to Islamophobia and anti-Muslim hate, on a scale of 0 to 1. This allows us to filter out the noise — because about 92% of what the pipeline picks up is general news that happens to contain keywords we track. Only about 8% is directly relevant.

**Step 4: The AI Prediction Model**
A machine learning model (Gradient Boosting — the same class of model used in everything from weather forecasting to credit scoring) is trained on patterns from the last 3.5 months of data. It looks at three things to predict how many relevant articles we'll see tomorrow:
- How many relevant articles appeared in the **last 7 days** (31% of the prediction weight)
- How many appeared in the **last 28 days** (30%)
- How many appeared **yesterday** (28%)

The rest — weekday patterns, confidence levels, etc. — makes up the remaining 11%.

The model's average error is about 6.26, which means a prediction of "1.34 articles tomorrow" should actually be read as "between 0 and 7." This is not precise yet — but it improves every day as more data feeds in. Think of it like a weather forecast that's still learning.

**Step 5: The Narrative Trend Forecast**
Beyond the numbers, we also generate a qualitative forecast — what we call the narrative trend analysis. This looks at the actual stories being published and predicts how the situation will develop:
- Who will react first (mosque committees, youth groups, monitoring bodies)
- How the media will frame the story (which narratives will dominate)
- Which public figures or influencers may drive the conversation
- A timeline of expected developments (72 hours, 1 week, 2 weeks)
- Key escalation risks to watch for

This is not an AI prediction — it's human-led analysis based on the clustering of real stories and established patterns of how these situations unfold.

**Step 6: The PDF Report**
Every morning at 8am, all of this data is assembled into a formatted PDF report and emailed. The report includes:
- A summary of key numbers (articles scanned, relevant articles found, sources monitored)
- A breakdown of incident types
- The AI prediction for the next 24 hours
- The top-scoring stories with relevance scores
- The narrative trend forecast with timeline and escalation risks
- A clear explanation of what the system can and cannot do

---

### What This System CAN Do

- Monitor 20+ sources 24 hours a day, 7 days a week, without human fatigue
- Flag relevant articles in real time as they are published
- Track whether reporting on anti-Muslim hate is trending up or down
- Surface key stories from specialist organisations that might otherwise be missed
- Provide early warning of emerging narratives that may lead to real-world harm
- Improve over time as more data is collected

### What This System CANNOT Do (Yet)

- It does not track every real-world hate incident — it tracks **news reports about them**. Many incidents go unreported or are not picked up by the sources we monitor.
- It does not verify whether an incident actually happened — it reads what was published. Journalism errors or misreporting can affect the data.
- It does not predict individual attacks — it predicts reporting patterns, which is not the same thing.
- The prediction model is still early-stage (3.5 months of training data). With a prediction error of 6.26, the daily forecast is directional rather than precise.

---

### What This Means for Protecting People

This system is an early warning intelligence tool — not a crystal ball. It tells us:

**Where the conversation is heading.** When we see a cluster of stories forming around a particular narrative — for example, "political rhetoric is fuelling hate crime" versus "the definition of Islamophobia goes too far" — we can anticipate how community tensions may escalate and where.

**Who is likely to react and how.** The trend forecast identifies which groups (mosques, youth networks, monitoring bodies) will be first to respond, and what form that response will take. This helps community leaders, police, and policymakers prepare.

**When to be most alert.** The timeline identifies key pressure points — Friday prayers, political statements, planned vigils — where the risk of confrontation or escalation is highest.

**What gaps remain.** The limitations section of the report is as important as the data. Knowing what we don't know — unreported incidents, unverified claims, model imprecision — is critical for making sound decisions.

---

### Technical Stack

| Component | Technology |
|---|---|
| Sources | 20 RSS/API feeds (BBC, Guardian, Tell MAMA, IRU, Google News, etc.) |
| Database | SQLite (1,323 articles, growing daily) |
| AI Model | HistGradientBoostingRegressor (scikit-learn) |
| Features | Rolling 7/28-day counts, lag features, weekday/month patterns |
| Training data | 108 daily aggregated rows (~3.5 months) |
| PDF generation | wkhtmltopdf (HTML → PDF at 300 DPI) |
| Delivery | msmtp → iCloud SMTP, emailed daily at 08:00 UK |
| Server | Contabo VPS, 8GB RAM, Ubuntu 24.04 |

---

*This report is generated automatically from live pipeline data and delivered every morning at 8am UK time. It is not a substitute for professional judgment — it is a tool to inform it.*

**GUARDED BY BULLY — DIGITAL THREAT RESPONSE UNIT**
**WE FEAR NO ONE**
