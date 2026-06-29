# File: 00_Index.md
# 🕌 Islamophobia Pipeline — Obsidian Vault

## 📋 Quick Navigation

| Section | Description |
|---------|-------------|
| [[01_Audit_Overview]] | Executive summary of the audit |
| [[02_Architecture]] | System architecture diagram & flow |
| [[03_Issues_Checklist]] | All 7 critical issues with fixes |
| [[04_Fixes]] | Complete patched code files |
| [[05_Setup]] | Environment, cron, dependencies |
| [[06_Testing]] | Test commands & validation |
| [[07_Archive]] | Original files & schema |

## 🔥 TL;DR

**7 critical issues found** in the Islamophobia Pipeline:

1. ❌ Schema mismatch in `alerts.py`
2. ❌ Hardcoded paths in `generate_brief.py`
3. ❌ Missing `simulations` table
4. ❌ Hardcoded font path
5. ❌ PostgreSQL vs SQLite conflict
6. ❌ Import inconsistency
7. ❌ SimHash stored as string

**All fixes** are in [[04_Fixes]].
