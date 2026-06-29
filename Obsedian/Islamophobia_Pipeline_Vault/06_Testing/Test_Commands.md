# Test Commands

## Database

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect("output/islamophobia_v3.sqlite3")
c = conn.cursor()
print("Total:", c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0])
print("Relevant >0.5:", c.execute("SELECT COUNT(*) FROM incidents WHERE relevance_score > 0.5").fetchone()[0])
conn.close()
"
```

## Alerts

```bash
python3 alerts.py --breaking-only
python3 alerts.py --email --breaking-only
python3 alerts.py --json
```
