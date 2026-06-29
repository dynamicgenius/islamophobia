# 🕌 Islamophobia Pipeline — Obsidian Vault

## 📋 Quick Navigation

| Section | Description |
|---------|-------------|
| [[01_Audit_Overview]] | Executive summary |
| [[02_Architectur[[04_Fixes_Inde[[04_Fixes_Index]]]] | System architecture |
| [[03_Issues_Checklist]] | ✅ ALL 7 ISSUES RESOLVED |
| [[04_Fixe[[04_Fixes_Inde[[04_Fixes_Index]]]] | Patched code files |
| [[05_Setup]] | Environment, cron, dependencies |
| [[06_Testing]] | Test commands |
| [[07_Archiv[[04_Fixes_Inde[[04_Fixes_Index]]]] | Schema reference |
| [[08_Deployment_Statu[[04_Fixes_Inde[[04_Fixes_Index]]]] | Production status |

---

## 🟢 CURRENT STATUS: FULLY OPERATIONAL

**✅ All 7 issues resolved as of 2026-06-27**

| Metric | Value |
|--------|-------|
| Sources | 20 |
| Total items | 375+ |
| High relevance | 21+ |
| Alerts | Working |
| Pipeline | Production-ready |

---

## 🚀 Quick Commands

```bash
# Run pipeline
conda activate islamophobia
python3 run_all.py

# Check alerts
python3 alerts.py --breaking-only
python3 alerts.py --threshold 0.5

# Generate daily brief
python3 generate_brief.py
