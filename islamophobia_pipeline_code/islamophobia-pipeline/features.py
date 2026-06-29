#!/usr/bin/env python3
"""
Islamophobia Pipeline — Feature Tagger
Adds categorical feature columns to pipeline data for analysis/ML.

Feature columns:
  tag_conflict  — mentions of Gaza/Israel/Palestine/Hamas (context marker)
  tag_protest   — protests/marches/rallies/demonstrations
  tag_assault   — physical attacks/assaults/vandalism/threats/abuse
  tag_online    — online hate / social media dimensions
  tag_policy    — government policy / legislation / definition
  tag_court     — court cases / sentencing / arrests / CPS
  tag_mosque    — mosque / Islamic centre / cemetery
  tag_education — schools / universities / education
  tag_hijab     — hijab / burqa / niqab / religious dress
"""

import os
import re
import json
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Optional ML model integration
try:
    import joblib
    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False

MODEL_DIR = Path('models')

OUT_DIR = Path(os.getenv('FEATURES_OUT', 'output'))

# Feature keyword patterns
FEATURE_PATTERNS = {
    'tag_conflict':  ['gaza', 'israel', 'palestine', 'hamas', 'west bank', 'hezbollah', 'iran'],
    'tag_protest':   ['protest', 'march', 'rally', 'demonstration', 'sit-in', 'vigil'],
    'tag_assault':   ['assault', 'attack', 'vandalism', 'threat', 'abuse', 'stab',
                      'fire', 'arson', 'bomb', 'terror'],
    'tag_online':    ['online', 'social media', 'twitter', 'x ', 'facebook', 'instagram',
                      'tiktok', 'youtube', 'telegram'],
    'tag_policy':    ['government', 'policy', 'legislation', 'definition', 'minister',
                      'mp says', 'home office', 'adviser', 'tsar', 'strategy',
                      'action plan', 'parliament'],
    'tag_court':     ['court', 'sentenced', 'jailed', 'arrest', 'prosecution',
                      'cps', 'crown court', 'magistrate', 'guilty', 'convict'],
    'tag_mosque':    ['mosque', 'islamic centre', 'muslim cemetery', 'muslim burial',
                      'madrasa', 'prayer room'],
    'tag_education': ['school', 'university', 'college', 'academy', 'education',
                      'teacher', 'student', 'classroom', 'curriculum'],
    'tag_hijab':     ['hijab', 'burqa', 'niqab', 'religious dress', 'face veil',
                      'headscarf'],
}


def tag_dataframe(df: pd.DataFrame, use_ml: bool = True) -> pd.DataFrame:
    """
    Add binary feature columns to a DataFrame based on title and content.
    Uses keyword patterns (always) + optional ML model predictions.
    Returns a copy with feature columns appended.
    """
    df = df.copy()

    # Build combined search text (lowercase)
    t_parts = []
    if 'title' in df.columns:
        t_parts.append(df['title'].fillna(''))
    if 'content' in df.columns:
        t_parts.append(df['content'].fillna(''))
    if 'source' in df.columns:
        t_parts.append(df['source'].fillna(''))

    if not t_parts:
        for feat in FEATURE_PATTERNS:
            df[feat] = 0
        df['tag_any_incident'] = 0
        return df

    t = t_parts[0].str.lower()
    for part in t_parts[1:]:
        t = t + ' ' + part.str.lower()

    # ── Keyword-based tagging (always runs) ──
    for feat, patterns in FEATURE_PATTERNS.items():
        pattern = '|'.join(re.escape(p) for p in patterns)
        df[feat] = t.str.contains(pattern, na=False).astype(int)

    df['tag_any_incident'] = ((df['tag_assault'] == 1) | (df['tag_mosque'] == 1)).astype(int)

    # ── ML-enhanced scoring (optional) ──
    if use_ml and HAS_JOBLIB and MODEL_DIR.exists():
        ml_labels = ['tag_assault', 'tag_policy', 'tag_mosque', 'tag_court',
                     'tag_any_incident']
        texts = t.values
        for label in ml_labels:
            model_path = MODEL_DIR / f'clf_{label}.joblib'
            if model_path.exists():
                try:
                    model = joblib.load(model_path)
                    preds = model.predict(texts)
                    probas = model.predict_proba(texts)
                    confidence = np.max(probas, axis=1)

                    # ML label: keep keyword tag, but add confidence score
                    df[f'{label}_ml'] = preds
                    df[f'{label}_conf'] = np.round(confidence, 3)

                    # Override keyword tag when ML is highly confident (>0.85) and disagrees
                    high_conf = confidence >= 0.85
                    df.loc[high_conf, label] = preds[high_conf]
                except Exception:
                    pass

    return df


def load_from_csv(path: str) -> pd.DataFrame:
    """Load items CSV and add feature tags."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Items CSV not found: {path}")
    df = pd.read_csv(path)
    return tag_dataframe(df)


def load_from_db(db_path: str, threshold: float = 0.0) -> pd.DataFrame:
    """Load items from SQLite DB and add feature tags."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Pipeline DB not found: {db_path}")
    conn = sqlite3.connect(db_path)
    query = 'SELECT source, title, url, published_at, fetched_at, source_type, relevance, content FROM sources'
    if threshold > 0:
        query += f' WHERE relevance >= {threshold}'
    query += ' ORDER BY relevance DESC'
    df = pd.read_sql_query(query, conn)
    conn.close()
    return tag_dataframe(df)


def build_features(infile: str = 'output/latest_items.csv',
                   outfile: str = 'features.csv',
                   db: Optional[str] = None,
                   threshold: float = 0.0,
                   use_ml: bool = True) -> str:
    """
    Build the features CSV from either a CSV infile or SQLite database.
    Returns the output file path.
    """
    if db:
        df = load_from_db(db, threshold=threshold)
    else:
        df = load_from_csv(infile)

    # If ML models exist and use_ml=True, re-tag with ML enhancement
    if use_ml and HAS_JOBLIB and (MODEL_DIR / 'clf_tag_any_incident.joblib').exists():
        from features import tag_dataframe
        df = tag_dataframe(df, use_ml=True)

    out_path = OUT_DIR / outfile
    df.to_csv(out_path, index=False)
    return str(out_path)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Islamophobia Pipeline — Feature Tagger')
    parser.add_argument('--csv', type=str, default='output/latest_items.csv',
                        help='Input CSV (default: output/latest_items.csv)')
    parser.add_argument('--db', type=str, default=None,
                        help='SQLite DB path (overrides CSV)')
    parser.add_argument('--out', type=str, default='features.csv',
                        help='Output file (default: features.csv)')
    parser.add_argument('--threshold', type=float, default=0.0,
                        help='Minimum relevance threshold (DB mode only)')
    parser.add_argument('--show-stats', action='store_true',
                        help='Print feature distribution stats')
    args = parser.parse_args()

    out = build_features(infile=args.csv, outfile=args.out,
                         db=args.db, threshold=args.threshold)

    if args.show_stats:
        df = pd.read_csv(out)
        print(f"\n📊 Feature Distribution ({len(df)} items)\n")
        feat_cols = [c for c in df.columns if c.startswith('tag_')]
        for col in feat_cols:
            count = df[col].sum()
            pct = count / len(df) * 100 if len(df) > 0 else 0
            print(f"  {col:20s}  {count:4d} items ({pct:5.1f}%)")
        print(f"\n  Output: {out}")

    print(out)


if __name__ == '__main__':
    main()
