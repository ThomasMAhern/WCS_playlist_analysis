import polars as pl
import sys

from utils.search_engine import PLAYLIST_DATA_FILE, PLAYLIST_TRACKS_DATA_FILE, TRACK_ADJACENT_DATA_FILE, SearchEngine

mode = sys.argv[1]

if mode == 'write':
    social_playlists = pl.scan_parquet(PLAYLIST_DATA_FILE)\
        .filter(pl.col('playlist.is_social_set'))\
        .filter(~pl.col('playlist.name').str.contains_any(['The Maine', 'delete', 'SPOTIFY']))\
        .select('playlist.id')

    songs_df = pl.scan_parquet(PLAYLIST_TRACKS_DATA_FILE)\
        .with_columns(pl.col('playlist_track.number').cast(pl.Int64))\
        .join(social_playlists, how='semi', on=['playlist.id'])\
        .sort('playlist.id', 'playlist_track.number')\
        .rolling(index_column='playlist_track.number', period='2i', group_by='playlist.id')\
        .agg(pl.col('track.id'))\
        .filter(pl.col('track.id').list.len().eq(2))\
        .group_by(pl.col('track.id'))\
        .agg(pl.col('playlist.id').n_unique().alias('playlist_count'))\
        .select(pl.col('track.id').list.get(0).alias('pair1.track.id'),
                pl.col('track.id').list.get(1).alias('pair2.track.id'),
                pl.col('playlist_count'))\
        .sort(['pair1.track.id', 'pair2.track.id'])
    # .sort('playlist_count', descending=True)

    songs_df.sink_parquet(TRACK_ADJACENT_DATA_FILE)
elif mode == 'load':
    songs_df = pl.scan_parquet(TRACK_ADJACENT_DATA_FILE)

print(songs_df.collect())

search_engine = SearchEngine()
search_engine.load_data()

print(search_engine.find_related_songs(
    direction='next',
    song_name='Josephine - Acoustic',
    artist_name='RITUAL',
).collect())
