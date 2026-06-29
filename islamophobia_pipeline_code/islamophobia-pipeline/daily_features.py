import pandas as pd


def build_daily_features(df):
    df = df.copy()
    if df.empty:
        return pd.DataFrame()

    df["day"] = pd.to_datetime(df["published_at"], errors="coerce").dt.date
    daily = (
        df.groupby("day")
        .agg(
            incidents=("incident_id", "count"),
            verified=("verified", "sum"),
            avg_confidence=("confidence", "mean"),
            avg_relevance=("relevance_score", "mean"),
            online_share=("online_flag", "mean"),
            offline_share=("offline_flag", "mean"),
            event_share=("event_flag", "mean"),
            conflict_share=("conflict_flag", "mean"),
            protest_share=("protest_flag", "mean"),
            far_right_share=("far_right_flag", "mean"),
        )
        .reset_index()
        .sort_values("day")
        .reset_index(drop=True)
    )

    daily["day"] = pd.to_datetime(daily["day"]).dt.date.astype(str)
    daily["weekday"] = pd.to_datetime(daily["day"]).dt.weekday
    daily["weekend_flag"] = (daily["weekday"] >= 5).astype(int)
    daily["month"] = pd.to_datetime(daily["day"]).dt.month

    for lag in [1, 7, 14, 28]:
        daily[f"lag_{lag}_incidents"] = daily["incidents"].shift(lag).fillna(0)
        daily[f"lag_{lag}_verified"] = daily["verified"].shift(lag).fillna(0)

    for win in [7, 28]:
        daily[f"rolling_{win}_incidents"] = daily["incidents"].rolling(win, min_periods=1).mean()
        daily[f"rolling_{win}_verified"] = daily["verified"].rolling(win, min_periods=1).mean()
        daily[f"rolling_{win}_online_share"] = daily["online_share"].rolling(win, min_periods=1).mean()
        daily[f"rolling_{win}_confidence"] = daily["avg_confidence"].rolling(win, min_periods=1).mean()

    daily["target_next_day_incidents"] = daily["incidents"].shift(-1)
    daily["target_next_7_day_incidents"] = daily["incidents"].rolling(7).sum().shift(-7)
    baseline = daily["rolling_7_incidents"].fillna(daily["incidents"].expanding().mean())
    daily["spike_label"] = (daily["incidents"] > baseline * 1.5).astype(int)

    return daily


def build_from_sqlite(conn, out_csv="output/features_daily.csv"):
    df = pd.read_sql_query("SELECT * FROM incidents", conn)
    feats = build_daily_features(df)
    feats.to_csv(out_csv, index=False)
    return out_csv


if __name__ == "__main__":
    print("feature builder ready")
