#!/usr/bin/env python3
"""
Stakeholder-ready incident forecasting pipeline.
Poisson + HGBR with calibration, prediction intervals, and interactive HTML dashboard.
"""

import pandas as pd
import numpy as np
from sklearn.linear_model import PoissonRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import joblib
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path


FEATURES = ["lag_1", "lag_7", "lag_28", "roll_7", "roll_28", "dow", "month", "day", "is_weekend"]


def make_features(df):
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    for lag in [1, 7, 28]:
        df[f"lag_{lag}"] = df["incident_count"].shift(lag)
    df["roll_7"] = df["incident_count"].shift(1).rolling(7).mean()
    df["roll_28"] = df["incident_count"].shift(1).rolling(28).mean()
    df["dow"] = df["date"].dt.dayofweek
    df["month"] = df["date"].dt.month
    df["day"] = df["date"].dt.day
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    return df


def train_models(df):
    """Train Poisson (scaled) and HGBR models. Returns (df_feat, data, poisson, gbr, metrics, eval_pack)."""
    df = make_features(df)
    data = df.dropna(subset=FEATURES + ["incident_count"]).copy()
    X = data[FEATURES]
    y = data["incident_count"].astype(float)
    split_idx = int(len(data) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    poisson = Pipeline([
        ("scale", StandardScaler()),
        ("model", PoissonRegressor(alpha=0.1, max_iter=2000))
    ])
    poisson.fit(X_train, y_train)
    pred_p = np.clip(poisson.predict(X_test), 0, None)

    gbr = HistGradientBoostingRegressor(loss="poisson", max_depth=4, learning_rate=0.05, random_state=42)
    gbr.fit(X_train, y_train)
    pred_g = np.clip(gbr.predict(X_test), 0, None)

    metrics = pd.DataFrame([
        {"model": "PoissonRegressor",
         "mae": mean_absolute_error(y_test, pred_p),
         "rmse": root_mean_squared_error(y_test, pred_p)},
        {"model": "HistGradientBoostingRegressor",
         "mae": mean_absolute_error(y_test, pred_g),
         "rmse": root_mean_squared_error(y_test, pred_g)},
    ])
    return df, data, poisson, gbr, metrics, (X_test, y_test, pred_p, pred_g)


def residual_interval(model, X_train, y_train, X_pred, z=1.28):
    """Compute forecast with 80% prediction interval from training residuals."""
    preds_train = np.clip(model.predict(X_train), 0, None)
    resid = y_train.values - preds_train
    sigma = float(np.std(resid, ddof=1)) if len(resid) > 1 else 0.0
    pred = float(np.clip(model.predict(X_pred)[0], 0, None))
    return pred, max(0.0, pred - z * sigma), pred + z * sigma, sigma


def forecast_next_day(df, model):
    """Forecast next day's incident count with prediction interval."""
    df = make_features(df)
    data = df.dropna(subset=FEATURES + ["incident_count"]).copy()
    last = df.dropna(subset=FEATURES).iloc[-1]
    X_next = pd.DataFrame([last[FEATURES].to_dict()])
    X_train = data[FEATURES]
    y_train = data["incident_count"].astype(float)
    pred, lower, upper, sigma = residual_interval(model, X_train, y_train, X_next)
    return {
        "basis_date": str(pd.to_datetime(last["date"]).date()),
        "forecast": pred,
        "forecast_lower": lower,
        "forecast_upper": upper,
        "residual_sigma": sigma,
    }


def calibration_summary(y_true, y_pred):
    """Bin predictions by quantile and compare mean predicted vs mean actual."""
    y_pred = np.asarray(y_pred)
    y_true = np.asarray(y_true)
    if len(y_true) < 10:
        return pd.DataFrame(columns=["bin", "pred_mean", "true_mean"])
    quantiles = pd.qcut(pd.Series(y_pred), q=min(5, len(y_pred)), duplicates="drop")
    tmp = pd.DataFrame({"bin": quantiles, "pred": y_pred, "true": y_true})
    return tmp.groupby("bin", observed=True).agg(
        pred_mean=("pred", "mean"), true_mean=("true", "mean")
    ).reset_index(drop=True)


def make_dashboard(df, metrics, forecast_df, output_dir="output"):
    """Generate an interactive Plotly HTML dashboard."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    df = df.reset_index(drop=True)
    # Build backcast predictions for the chart
    feat_df = make_features(df.copy())
    train_data = feat_df.dropna(subset=FEATURES + ["incident_count"]).copy()
    X_all = train_data[FEATURES]
    y_all = train_data["incident_count"]

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=("Actual vs Predicted (In-Sample)", "Model Metrics",
                        "Next-Day Forecast with 80% CI", "Residual Distribution")
    )

    # Row 1 Col 1: Actual vs predicted (in-sample, using HGBR)
    try:
        best_model = joblib.load(out / "gbr_stakeholder.joblib")
        y_pred_all = np.clip(best_model.predict(X_all), 0, None)
        fig.add_trace(go.Scatter(x=train_data["date"], y=y_all, name="Actual",
                                 line=dict(color="#1f77b4")), row=1, col=1)
        fig.add_trace(go.Scatter(x=train_data["date"], y=y_pred_all, name="Predicted (HGBR)",
                                 line=dict(color="#ff7f0e")), row=1, col=1)
    except Exception:
        fig.add_trace(go.Scatter(x=train_data["date"], y=y_all, name="Actual",
                                 line=dict(color="#1f77b4")), row=1, col=1)

    # Row 1 Col 2: Bar chart of MAE / RMSE
    metrics_long = metrics.melt(id_vars=["model"], value_vars=["mae", "rmse"],
                                var_name="metric", value_name="score")
    for m in metrics_long["model"].unique():
        sub = metrics_long[metrics_long["model"] == m]
        fig.add_trace(go.Bar(x=sub["metric"], y=sub["score"], name=m), row=1, col=2)

    # Row 2 Col 1: Forecast with confidence interval
    if not forecast_df.empty:
        f = forecast_df.iloc[0]
        f_date = pd.to_datetime(f.get("basis_date", ""))
        fig.add_trace(go.Scatter(x=[f_date], y=[f["forecast"]], name="Forecast",
                                 mode="markers+lines", marker=dict(size=10, color="#ff7f0e")),
                      row=2, col=1)
        fig.add_trace(go.Scatter(x=[f_date, f_date],
                                 y=[f.get("forecast_lower", 0), f.get("forecast_upper", 0)],
                                 name="80% CI", mode="lines",
                                 line=dict(color="rgba(255,127,14,0.3)", width=8),
                                 showlegend=True), row=2, col=1)

    # Row 2 Col 2: Residual histogram
    resid = y_all - y_all.rolling(7, min_periods=1).mean() if len(y_all) > 7 else pd.Series([0]*len(y_all))
    fig.add_trace(go.Histogram(x=resid.dropna(), name="Residuals", marker_color="#9467bd",
                               nbinsx=20), row=2, col=2)

    fig.update_layout(height=900, width=1200,
                      title_text="Incident Forecast Stakeholder Dashboard",
                      barmode="group")
    html_path = out / "stakeholder_dashboard.html"
    fig.write_html(str(html_path), include_plotlyjs="cdn")
    print(f"[Dashboard] Saved: {html_path}")
    return html_path


def run_pipeline(input_csv, output_dir="output"):
    """Full pipeline: train, forecast, dashboard, persist models."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(input_csv)
    if not {"date", "incident_count"}.issubset(df.columns):
        raise ValueError("Input CSV must contain 'date' and 'incident_count' columns")

    df_feat, data, poisson, gbr, metrics, eval_pack = train_models(df)
    X_test, y_test, pred_p, pred_g = eval_pack

    # Calibration error: absolute difference between mean prediction and mean actual
    metrics["calibration_error"] = [
        float(abs(y_test.mean() - pred_p.mean())),
        float(abs(y_test.mean() - pred_g.mean())),
    ]

    forecast_p = forecast_next_day(df, poisson)
    forecast_g = forecast_next_day(df, gbr)
    forecast_df = pd.DataFrame([
        {"model": "PoissonRegressor", **forecast_p},
        {"model": "HistGradientBoostingRegressor", **forecast_g},
    ])
    forecast_df["date"] = pd.to_datetime(forecast_df["basis_date"]) + pd.Timedelta(days=1)

    # Persist
    joblib.dump(poisson, out / "poisson_stakeholder.joblib")
    joblib.dump(gbr, out / "gbr_stakeholder.joblib")
    metrics.to_csv(out / "stakeholder_model_metrics.csv", index=False)
    forecast_df.to_csv(out / "stakeholder_next_day_forecast.csv", index=False)

    # Dashboard
    make_dashboard(df_feat.dropna(subset=["incident_count"]), metrics, forecast_df, output_dir=output_dir)

    return metrics, forecast_df


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Stakeholder-ready incident forecasting pipeline")
    parser.add_argument("input_csv", help="CSV with date,incident_count")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    args = parser.parse_args()
    metrics, forecast_df = run_pipeline(args.input_csv, args.output_dir)
    print(metrics.to_string(index=False))
    print(forecast_df.to_string(index=False))
