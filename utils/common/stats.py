"""Utilities for calculating database statistics."""
from typing import Literal, overload

import polars as pl


@overload
def count_n_unique(data: pl.LazyFrame, columns: list[str], single_key: Literal[True]) -> int:
    """Count the number of unique rows, using the specified columns as the composite primary key."""
    pass


@overload
def count_n_unique(data: pl.LazyFrame, columns: list[str], single_key: Literal[False] = False) -> list[int]:
    """Count the number of unique values in the specified columns."""
    pass


def count_n_unique(data: pl.LazyFrame, columns: list[str], single_key: bool = False) -> int | list[int]:
    """Count the number of unique values in the specified columns."""
    if single_key:
        # Count the number of unique combinations of the specified columns
        return list(data.select(pl.concat_list(columns).n_unique().alias('count'))
                    .collect(engine='streaming')
                    .iter_rows())[0][0]

    else:
        # Count each column separately
        return list(list(data.select(pl.n_unique(*columns))
                         .collect(engine='streaming')
                         .iter_rows())[0])
