"""
Feature Builder — builds daily feature vectors from incident data.
Alias for daily_features module.
"""
from daily_features import build_daily_features, build_from_sqlite

__all__ = ['build_daily_features', 'build_from_sqlite']
