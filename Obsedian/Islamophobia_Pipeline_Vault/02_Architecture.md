# System Architecture

## Flow Diagram

```
CRON: Every 2 hours
  └── run_all.py → pipeline_runner.py
       ├── 1. Ingest from 20+ sources
       ├── 2. Deduplicate (Union-Find + fuzzy matching)
       ├── 3. Classify (keyword + ML-enhanced)
       ├── 4. Build daily features
       ├── 5. Train ML models (Poisson + HGBR)
       └── 6. Predict next 24h

CRON: Every 15 minutes
  └── alerts.py
       ├── Check for breaking stories
       └── Email if CRITICAL/HIGH severity

CRON: Daily at 8:00 AM
  └── generate_brief.py
       ├── Query DB for stats
       ├── Generate HTML report
       ├── Convert to PDF with wkhtmltopdf
       └── Email to ibbiy@icloud.com
```

## Database Schema (v3)

```sql
sources       -- Source definitions (20+ sources)
incidents     -- All articles with metadata
incident_tags -- Tagging (tag, value)
daily_metrics -- Daily aggregations
events        -- Known events for context
model_runs    -- ML model metadata
pipeline_runs -- Pipeline execution logs
```
