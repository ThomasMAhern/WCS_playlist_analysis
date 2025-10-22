"""Utility functions for reordering columns in polars dataframes."""
import polars as pl


def pull_columns_to_front(*columns: str) -> list[pl.Expr]:
    return [
        pl.col(columns),
        pl.all().exclude(columns),
    ]
