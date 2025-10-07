import polars as pl

source_data = pl.scan_parquet('data_playlists.parquet')

playlists = source_data.select(
    pl.col('playlist_id').alias('playlist.id'),
    pl.col('name').alias('playlist.name'),
    pl.col('owner.id'),
    pl.col('owner.display_name').alias('owner.name')
).unique()

q = playlists

print(q.limit(50).collect())

print(q.schema)
