#!/usr/bin/env python3
"""
Train Poisson + HGBR count models and forecast next-day incidents.
Replaces the old RandomForest-based train.py.
Uses: StandardScaler pipeline, is_weekend feature, calibration metrics.
"""

import pandas as pd
import numpy as np
from sklearn.linear_model import PoissonRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import joblib
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


def fit_models(df):
    """Train Poisson (scaled) and HGBR models. Returns (df_feat, data, poisson, gbr, metrics_df, feature_cols)."""
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

    calibration_error = [float(abs(y_test.mean() - pred_p.mean())),
                         float(abs(y_test.mean() - pred_g.mean()))]

    metrics = pd.DataFrame([
        {"model": "PoissonRegressor",
         "mae": mean_absolute_error(y_test, pred_p),
         "rmse": root_mean_squared_error(y_test, pred_p),
         "calibration_error": calibration_error[0]},
        {"model": "HistGradientBoostingRegressor",
         "mae": mean_absolute_error(y_test, pred_g),
         "rmse": root_mean_squared_error(y_test, pred_g),
         "calibration_error": calibration_error[1]},
    ])
    return df, data, poisson, gbr, metrics, FEATURES


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
        "forecast": round(pred, 2),
        "forecast_lower": round(lower, 2),
        "forecast_upper": round(upper, 2),
        "residual_sigma": round(sigma, 3),
        "basis_date": str(pd.to_datetime(last["date"]).date())
    }


def run_pipeline(input_csv, output_dir="output"):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(input_csv)
    if not {"date", "incident_count"}.issubset(df.columns):
        raise ValueError("Input CSV must contain 'date' and 'incident_count' columns")

    df_feat, data, poisson, gbr, metrics, feature_cols = fit_models(df)

    # Persist models
    joblib.dump(poisson, out / "poisson_regressor.joblib")
    joblib.dump(gbr, out / "hist_gbr_poisson.joblib")
    metrics.to_csv(out / "model_metrics.csv", index=False)

    forecast_p = forecast_next_day(df, poisson)
    forecast_g = forecast_next_day(df, gbr)

    forecast_df = pd.DataFrame([
        {"model": "PoissonRegressor", **forecast_p},
        {"model": "HistGradientBoostingRegressor", **forecast_g},
    ])
    forecast_df.to_csv(out / "next_day_forecast.csv", index=False)

    # Pick best model (lower MAE)
    best_idx = metrics["mae"].idxmin()
    best_model_name = metrics.loc[best_idx, "model"]
    best_forecast = forecast_p if best_model_name == "PoissonRegressor" else forecast_g

    return metrics, forecast_df, best_model_name, best_forecast


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Train count models and forecast next day incidents")
    parser.add_argument("input_csv", help="CSV with date,incident_count")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    args = parser.parse_args()
    metrics, forecast_df, best_model, best_forecast = run_pipeline(args.input_csv, args.output_dir)
    print("Model Metrics:")
    print(metrics.to_string(index=False))
    print("\nForecast:")
    print(forecast_df.to_string(index=False))
    print(f"\nBest model: {best_model}")
    print(f"Next day forecast: {best_forecast['forecast']} (CI: {best_forecast['forecast_lower']}-{best_forecast['forecast_upper']})")
