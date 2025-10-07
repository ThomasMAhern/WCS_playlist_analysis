import polars as pl
import polars.selectors as cs

source_data = pl.scan_parquet('data_playlists.parquet')

playlists = source_data.select(
    pl.col('playlist_id').alias('playlist.id'),
    pl.col('name').alias('playlist.name'),
    pl.col('owner.id'),
    pl.col('owner.display_name').alias('owner.name'),
    # Only required for extended data below
    pl.col('location').alias('playlist.location'),
).unique()

from utils.playlist_classifiers import extract_dates_from_name

playlists_extended = playlists.with_columns(
    extract_dates_from_name(pl.col('playlist.name')).cast(pl.List(pl.Categorical)).alias('playlist.extracted_date'),
    pl.col('playlist.location').str.split(' - ').list.get(0, null_on_oob=True).alias('playlist.region'),
    pl.col('playlist.location').str.split(' - ').list.get(1, null_on_oob=True).alias('playlist.country')
).select(cs.all() - cs.by_name('playlist.location'))

q = playlists_extended

print(q.limit(50).collect())

print(q.schema)
