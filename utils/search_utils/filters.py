import polars as pl

IntoExpr = str | list[str] | pl.Expr


def into_expr(expr: IntoExpr) -> pl.Expr:
    if isinstance(expr, str):
        return pl.col(expr)
    if isinstance(expr, list):
        return pl.col(expr)
    return expr


def or_filter(*filters: pl.Expr | None) -> pl.Expr | None:
    expr: pl.Exp | None = None
    for filter in filters:
        if filter is not None:
            expr = expr | filter if expr is not None else filter
    return expr


def create_text_filter(
    filter_expression: str | list[str] | None,
    column: IntoExpr,
    *,
    ascii_case_insensitive: bool = True
) -> pl.Expr | None:
    """Parse a filter expression for a text column."""
    if filter_expression is None:
        return None

    if isinstance(filter_expression, list):
        if ascii_case_insensitive:
            values = [item.lower() for item in filter_expression if item]
        else:
            values = list(filter(bool, filter_expression))
    else:
        if ascii_case_insensitive:
            values = list(
                filter(bool, filter_expression.strip().lower().split(',')))
        else:
            values = list(filter(bool, filter_expression.strip().split(',')))

    if not values:
        return None

    return into_expr(column).cast(pl.String).str.contains_any(values, ascii_case_insensitive=ascii_case_insensitive)


def create_date_filter(filter_expression: str, column: IntoExpr) -> pl.Expr | None:
    """Parse a filter expression for a date column"""
    return create_text_filter(
        filter_expression,
        into_expr(column).dt.to_string(),
        ascii_case_insensitive=False)
