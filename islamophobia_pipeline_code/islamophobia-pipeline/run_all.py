"""
Islamophobia Pipeline — Full Orchestrator
Single entry point: ensures schema, ingests 20 sources, builds features,
trains model, predicts next day, and generates alerts.

Usage:
    python3 run_all.py
"""

from pipeline_runner import run as full_pipeline
import json


def run_all(db_path='output/islamophobia_v3.sqlite3'):
    print("=" * 60)
    print("Islamophobia Pipeline — Full Run")
    print("=" * 60)
    result = full_pipeline(db_path=db_path)
    print("=" * 60)
    print("Pipeline complete.")
    print("=" * 60)
    return result


if __name__ == '__main__':
    result = run_all()
    print(json.dumps(result, indent=2))
