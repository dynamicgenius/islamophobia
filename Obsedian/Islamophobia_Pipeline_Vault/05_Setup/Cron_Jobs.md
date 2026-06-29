# Cron Jobs

Add to `crontab -e`:

```bash
# Pipeline ingestion (every 2 hours)
0 */2 * * * cd /path/to/pipeline && python3 run_all.py >> logs/pipeline_$(date +\%Y\%m\%d).log 2>&1

# Daily brief (8:00 AM)
0 8 * * * cd /path/to/pipeline && python3 generate_brief.py >> logs/brief_$(date +\%Y\%m\%d).log 2>&1

# Breaking alerts (every 15 minutes)
*/15 * * * * cd /path/to/pipeline && python3 alerts.py --email --breaking-only >> logs/alerts_$(date +\%Y\%m\%d).log 2>&1
```
