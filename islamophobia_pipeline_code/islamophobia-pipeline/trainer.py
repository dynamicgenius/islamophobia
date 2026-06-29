"""
Trainer module — trains and runs predictions.
Alias for train module.
"""
from train import train, predict_next, train_from_db, inspect

__all__ = ['train', 'predict_next', 'train_from_db', 'inspect']
