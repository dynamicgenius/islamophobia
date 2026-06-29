# Islamophobia Pipeline v3

A Python pipeline that ingests source articles, stores incidents in SQLite, builds daily features, trains count models, and forecasts next-day incident counts.

## What it does

1. Ensures the SQLite schema exists.
2. Ingests RSS and HTML sources.
3. Upserts sources and incidents into the database.
4. Builds daily aggregate features.
5. Trains Poisson and HistGradientBoosting count models.
6. Produces a next-day forecast and model metrics.

## Project structure

```text
islamophobia_pipeline_code/
├── islamophobia-pipeline/
│   ├── alerts.py
│   ├── daily_features.py
│   ├── db_schema.sql
│   ├── db_utils.py
│   ├── dedup.py
│   ├── feature_builder.py
│   ├── features.py
│   ├── incident_ml_model.py
│   ├── ingest_pipeline.py
│   ├── pipeline.py
│   ├── pipeline_runner.py
│   ├── run_all.py
│   ├── send_prediction_email.py
│   ├── send_simulation_report.py
│   ├── train.py
│   └── trainer.py
├── opt/
│   └── trade-bridge/
│       ├── final_report_template.html
│       ├── generate_brief.py
│       └── panel_explanation.md
└── generate_brief.py
