#!/usr/bin/env python3
"""
Clean, verify, and deduplicate incident reports for Islamophobia Pipeline v3.
Uses difflib.SequenceMatcher for fuzzy matching with Union-Find clustering.
"""

import pandas as pd
import numpy as np
import re
from difflib import SequenceMatcher
from pathlib import Path


def clean_text(x):
    if pd.isna(x):
        return ""
    x = str(x).lower().strip()
    x = re.sub(r"\s+", " ", x)
    x = re.sub(r"[^a-z0-9\s\-\.,\/\(\)]", "", x)
    return x


def normalize_date(x):
    if pd.isna(x) or str(x).strip() == "":
        return pd.NaT
    # Strip timezone info before normalizing
    dt = pd.to_datetime(x, errors="coerce", utc=False)
    if pd.notna(dt):
        dt = dt.tz_localize(None) if dt.tz is not None else dt
    return dt.normalize() if pd.notna(dt) else pd.NaT


def sim(a, b):
    a = clean_text(a)
    b = clean_text(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def source_confidence(source_type, verified):
    source_type = clean_text(source_type)
    verified = str(verified).strip().lower() in {"1", "true", "yes", "y", "verified"}
    base = {
        "police": 0.95,
        "court": 0.98,
        "official": 0.90,
        "ngo": 0.75,
        "media": 0.60,
        "social": 0.40,
        "victim": 0.70,
        "other": 0.50,
        "unknown": 0.50,
    }.get(source_type, 0.50)
    if verified:
        base += 0.05
    return float(min(base, 1.0))


def source_weight(source_type):
    source_type = clean_text(source_type)
    return {
        "police": 1.00,
        "court": 1.00,
        "official": 0.95,
        "ngo": 0.80,
        "victim": 0.75,
        "media": 0.60,
        "social": 0.40,
        "other": 0.50,
        "unknown": 0.50,
    }.get(source_type, 0.50)


def incident_similarity(a, b, quick_check=False):
    keys_text = ["location", "incident_type", "headline", "description", "target"]

    if quick_check:
        # Fast pre-filter: check if type and at least one other field has reasonable token overlap
        type_a = clean_text(a.get("incident_type", ""))
        type_b = clean_text(b.get("incident_type", ""))
        if type_a != type_b:
            return 0.0
        # Quick headline overlap check (cheaper than full SequenceMatcher)
        hl_a = clean_text(a.get("headline", ""))
        hl_b = clean_text(b.get("headline", ""))
        if not hl_a or not hl_b:
            return 0.0
        # At least some word overlap needed
        words_a = set(hl_a.split())
        words_b = set(hl_b.split())
        if not words_a or not words_b:
            return 0.0
        if len(words_a & words_b) / max(len(words_a), len(words_b)) < 0.15:
            return 0.0

    scores = [sim(a.get(k, ""), b.get(k, "")) for k in keys_text]
    da, db = normalize_date(a.get("date")), normalize_date(b.get("date"))
    if pd.notna(da) and pd.notna(db):
        day_diff = abs((da - db).days)
        date_score = 1.0 if day_diff == 0 else 0.75 if day_diff <= 1 else 0.4 if day_diff <= 3 else 0.0
    else:
        date_score = 0.0
    scores.append(date_score)
    scores.append(min(source_weight(a.get("source_type")), source_weight(b.get("source_type"))))
    return float(np.mean(scores))


def normalize_incident_schema(df):
    df = df.copy()
    rename_map = {
        "datetime": "date",
        "reported_date": "date",
        "incident": "incident_type",
        "type": "incident_type",
        "title": "headline",
        "summary": "description",
        "loc": "location",
        "place": "location",
        "src_type": "source_type",
        "source": "source_name",
        "is_verified": "verified",
    }
    df = df.rename(columns={c: rename_map.get(c, c) for c in df.columns})
    for col in ["headline", "description", "location", "incident_type", "source_type", "source_name", "target"]:
        if col not in df.columns:
            df[col] = ""
    if "verified" not in df.columns:
        df["verified"] = False
    if "date" not in df.columns:
        df["date"] = pd.NaT
    for col in ["headline", "description", "location", "incident_type", "source_type", "source_name", "target"]:
        df[col] = df[col].apply(clean_text)
    df["date"] = df["date"].apply(normalize_date)
    df["verified"] = df["verified"].astype(str).str.lower().isin(["1", "true", "yes", "y", "verified"])
    return df


def add_quality_fields(df):
    df = df.copy()
    df["source_confidence"] = df.apply(lambda r: source_confidence(r.get("source_type"), r.get("verified")), axis=1)
    df["record_confidence"] = np.where(df["verified"], 1.0, df["source_confidence"])
    df["verification_status"] = np.select(
        [df["verified"], df["source_confidence"] >= 0.75],
        ["verified", "probable"],
        default="unverified"
    )
    return df


def assign_clusters(df, threshold=0.82):
    df = df.copy().reset_index(drop=True)
    n = len(df)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Pre-filter: group by date to reduce O(n²) comparisons
    df["_date_norm"] = df["date"].apply(lambda d: d.date() if pd.notna(d) else None)
    date_groups = df.groupby("_date_norm", sort=False)
    comparisons = 0

    for date_val, g in date_groups:
        idxs = g.index.tolist()
        for ii in range(len(idxs)):
            for jj in range(ii + 1, len(idxs)):
                i, j = idxs[ii], idxs[jj]
                if incident_similarity(df.loc[i].to_dict(), df.loc[j].to_dict(), quick_check=True) >= threshold:
                    union(i, j)
                comparisons += 1

    # Also compare adjacent date groups for close-timeline duplicates
    date_list = sorted([d for d in date_groups.groups.keys() if d is not None])
    for k in range(len(date_list) - 1):
        d1, d2 = date_list[k], date_list[k + 1]
        day_diff = abs((d1 - d2).days)
        if day_diff <= 3:
            g1_idxs = date_groups.get_group(d1).index.tolist()
            g2_idxs = date_groups.get_group(d2).index.tolist()
            for i in g1_idxs:
                for j in g2_idxs:
                    if incident_similarity(df.loc[i].to_dict(), df.loc[j].to_dict(), quick_check=True) >= threshold:
                        union(i, j)
                    comparisons += 1

    print(f"[Dedup] {comparisons} comparisons for {n} records")

    df = df.drop(columns=["_date_norm"])
    roots = [find(i) for i in range(n)]
    root_to_cluster = {}
    cluster_ids = []
    counter = 1
    for r in roots:
        if r not in root_to_cluster:
            root_to_cluster[r] = f"INC-{counter:06d}"
            counter += 1
        cluster_ids.append(root_to_cluster[r])
    df["canonical_id"] = cluster_ids
    return df


def merge_cluster(df):
    rows = []
    for cid, g in df.groupby("canonical_id", sort=True):
        g = g.copy()
        g["_rank"] = g["verified"].astype(int) * 10 + g["source_confidence"]
        best = g.sort_values(["_rank", "date"], ascending=[False, True]).iloc[0].to_dict()
        best["duplicate_count"] = int(len(g))
        best["verification_status"] = (
            "verified" if g["verified"].any()
            else ("probable" if g["source_confidence"].max() >= 0.75 else "unverified")
        )
        best["merged_sources"] = " | ".join(
            sorted(set([x for x in g.get("source_name", pd.Series(dtype=str)).fillna("").astype(str).tolist() if x]))
        )
        best["merged_source_types"] = " | ".join(
            sorted(set([x for x in g.get("source_type", pd.Series(dtype=str)).fillna("").astype(str).tolist() if x]))
        )
        if pd.notna(g["date"]).any():
            best["date_first_seen"] = pd.to_datetime(g["date"]).min()
            best["date_last_seen"] = pd.to_datetime(g["date"]).max()
        else:
            best["date_first_seen"] = pd.NaT
            best["date_last_seen"] = pd.NaT
        rows.append(best)
    out = pd.DataFrame(rows)
    if "_rank" in out.columns:
        out = out.drop(columns=["_rank"])
    return out.sort_values(["date_first_seen", "canonical_id"], na_position="last").reset_index(drop=True)


def build_audit_log(df):
    audit = []
    for cid, g in df.groupby("canonical_id", sort=True):
        idxs = g.index.to_list()
        for i in range(len(idxs)):
            for j in range(i + 1, len(idxs)):
                a, b = df.loc[idxs[i]], df.loc[idxs[j]]
                audit.append({
                    "canonical_id": cid,
                    "row_a": int(idxs[i]),
                    "row_b": int(idxs[j]),
                    "similarity": round(incident_similarity(a.to_dict(), b.to_dict(), quick_check=True), 3),
                    "source_a": a.get("source_name", ""),
                    "source_b": b.get("source_name", ""),
                    "verified_a": bool(a.get("verified", False)),
                    "verified_b": bool(b.get("verified", False)),
                })
    return pd.DataFrame(audit)


def add_prediction_interval(df, y_col="incident_count", pred_col="forecast", residual_col="residual", z=1.28):
    df = df.copy()
    if residual_col not in df.columns and y_col in df.columns and pred_col in df.columns:
        df[residual_col] = df[y_col] - df[pred_col]
    sigma = float(df[residual_col].std(ddof=1)) if residual_col in df.columns and len(df) > 1 else 0.0
    df["forecast_lower"] = np.maximum(0, np.round(df[pred_col] - z * sigma, 0))
    df["forecast_upper"] = np.round(df[pred_col] + z * sigma, 0)
    df["forecast_sigma"] = sigma
    return df


def process_incidents(input_path, output_dir="output", threshold=0.82):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(input_path)
    df = normalize_incident_schema(df)
    df = add_quality_fields(df)
    df = assign_clusters(df, threshold=threshold)
    audit = build_audit_log(df)
    cleaned = merge_cluster(df)
    cleaned_path = output_dir / "incidents_cleaned.csv"
    audit_path = output_dir / "incidents_audit_log.csv"
    cleaned.to_csv(cleaned_path, index=False)
    audit.to_csv(audit_path, index=False)
    return cleaned, audit


def dedup_incidents_db(db_path: str, threshold=0.82) -> tuple:
    """Load incidents from SQLite, deduplicate, return (cleaned_df, audit_df)."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT
            incident_id,
            title as headline,
            incident_type,
            location_text as location,
            published_at as date,
            summary as description,
            verified,
            relevance_score as score,
            source_id
        FROM incidents
    """, conn)
    src_df = pd.read_sql_query(
        "SELECT source_id, source_name, source_type FROM sources", conn
    )
    df = df.merge(src_df[['source_id', 'source_type', 'source_name']], on='source_id', how='left')
    conn.close()
    if df.empty:
        return df, pd.DataFrame()
    df = normalize_incident_schema(df)
    df = add_quality_fields(df)
    df = assign_clusters(df, threshold=threshold)
    audit = build_audit_log(df)
    cleaned = merge_cluster(df)
    return cleaned, audit


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Clean, verify, and deduplicate incident reports")
    parser.add_argument("input_csv", help="Raw incident CSV path")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    parser.add_argument("--threshold", type=float, default=0.82, help="Deduplication similarity threshold")
    args = parser.parse_args()
    cleaned, audit = process_incidents(args.input_csv, args.output_dir, args.threshold)
    print(f"Saved {len(cleaned)} cleaned rows and {len(audit)} audit rows")
