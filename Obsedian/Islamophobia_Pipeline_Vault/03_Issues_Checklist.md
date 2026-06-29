# Issues Checklist — All 7 Issues RESOLVED ✅

**Status:** All issues fixed as of 2026-06-27
**Pipeline:** Fully operational with real data

---

## ✅ Issue #1: Schema Mismatch in `alerts.py`

**Status:** ✅ RESOLVED

**Fix applied:** Query updated to use JOIN between `incidents` and `sources`

---

## ✅ Issue #2: Hardcoded Paths in `generate_brief.py`

**Status:** ✅ RESOLVED

**Fix applied:** Now uses environment variables

---

## ✅ Issue #3: Missing `simulations` Table

**Status:** ✅ RESOLVED (Not needed)

---

## ✅ Issue #4: Hardcoded Font Path

**Status:** ✅ RESOLVED

---

## ✅ Issue #5: PostgreSQL vs SQLite Conflict

**Status:** ✅ RESOLVED (Using SQLite exclusively)

---

## ✅ Issue #6: Import Inconsistency

**Status:** ✅ RESOLVED

---

## ✅ Issue #7: SimHash Stored as String

**Status:** ✅ RESOLVED

---

## Additional Fixes Applied

| Fix | Status |
|-----|--------|
| Added `article_url` column | ✅ |
| RSS parser captures article URLs | ✅ |
| Removed test data | ✅ |
| Created `db_schema.sql` | ✅ |
| Conda environment working | ✅ |
| All 20 sources ingesting | ✅ |
| Alerts showing real data | ✅ |

---

**Last Updated:** 2026-06-27
