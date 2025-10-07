import polars as pl
import polars.selectors as cs

from utils.playlist_classifiers import extract_dates_from_name
from utils.additional_data import actual_wcs_djs

source_data = pl.scan_parquet('data_playlists.parquet')

playlists = source_data.select(
    pl.col('playlist_id').alias('playlist.id'),
    pl.col('name').alias('playlist.name'),
    pl.col('owner.id'),
    pl.col('owner.display_name').alias('owner.name'),
    # Only required for extended data below
    pl.col('location').alias('playlist.location'),
).unique()

_is_social_set = (
    pl.col('playlist.extracted_date').list.len().gt(0)
    | pl.col('playlist.name').str.contains_any(['social', 'party', 'soir'], ascii_case_insensitive=True)
)

_is_wcs_dj = (
    pl.col('owner.id').str.contains_any(
        actual_wcs_djs, ascii_case_insensitive=True)
    | pl.col('owner.name').cast(pl.String).eq('Connie Wang')
    | pl.col('owner.name').cast(pl.String).eq('Koichi Tsunoda')
)

playlists_extended = playlists.with_columns(
    extract_dates_from_name(pl.col('playlist.name')).cast(
        pl.List(pl.Categorical)).alias('playlist.extracted_date'),
    pl.col('playlist.location').str.split(' - ').list.get(
        0, null_on_oob=True).alias('playlist.region'),
    pl.col('playlist.location').str.split(' - ').list.get(
        1, null_on_oob=True).alias('playlist.country'),
).with_columns(
    _is_social_set.alias('playlist.is_social_set'),
    _is_wcs_dj.alias('owner.is_wcs_dj'),
).select(cs.all() - cs.by_name('playlist.location'))

q = playlists_extended

print(q.limit(50).collect())

print(q.schema)
