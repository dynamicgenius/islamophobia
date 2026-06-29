# Audit Overview — Islamophobia Pipeline

## Executive Summary

**Date:** 2026-06-27 | **System:** Islamophobia Pipeline v3

### ✅ What Works Well

- Multi-source ingestion (RSS, HTML, Police UK API, PDF with OCR)
- Smart deduplication (Union-Find + fuzzy matching)
- Comprehensive feature engineering (lags, rolling windows, entropy)
- Modern ML (PoissonRegressor + HistGradientBoostingRegressor)
- Actionable outputs (email alerts, PDF reports, JSON/CSV)

### ❌ Critical Issues Found

| # | Issue | Severity |
|---|-------|----------|
| 1 | Schema mismatch in `alerts.py` | 🔴 Critical |
| 2 | Hardcoded paths in `generate_brief.py` | 🔴 Critical |
| 3 | Missing `simulations` table | 🟠 High |
| 4 | Hardcoded font path | 🟡 Medium |
| 5 | PostgreSQL vs SQLite conflict | 🟡 Medium |
| 6 | Import inconsistency | 🟢 Low |
| 7 | SimHash stored as string | 🟢 Low |

### 📊 System Metrics

| Metric | Value |
|--------|-------|
| Sources monitored | 20 |
| Articles in DB | 1,323 |
| Relevant articles | 109 |
| Training data | 108 days |
| ML model | HGBR (Poisson) |
| Prediction error (MAE) | ~6.26 |
