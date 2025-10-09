import polars as pl
import sys

from utils.search_engine import TRACK_DATA_FILE, TRACK_LYRICS_DATA_FILE, SearchEngine

if len(sys.argv) >= 2:
    mode = sys.argv[1] or 'load'
else:
    mode = 'load'

if mode == 'write':
    temp_file = 'temp_song_metadata_by_track_and_artist.parquet'

    print(f'Writing {temp_file}...')
    tracks = pl.scan_parquet(TRACK_DATA_FILE)\
        .select('track.id', 'track.name', 'track.artists.name')\
        .sort(['track.name', 'track.artists.name'])\
        .sink_parquet(temp_file)

    print(f'Reading {temp_file}...')
    tracks = pl.scan_parquet(temp_file)

    lyrics = pl.scan_parquet('song_lyrics.parquet')\
        .join(tracks,
              how='inner',
              left_on=['song', 'artist'],
              right_on=['track.name', 'track.artists.name'])\
        .select(pl.col('track.id'),
                pl.col('lyrics').alias('track.lyrics'))\
        .unique('track.id')\
        .sort('track.id')

    print(f'Writing {TRACK_LYRICS_DATA_FILE}...')
    lyrics.sink_parquet(TRACK_LYRICS_DATA_FILE)
    print('Done.')

search_engine = SearchEngine()
search_engine.load_data()

q = search_engine.find_songs(
    song_name='Back',
    artist_name='',
    playlist_in_result=False,
    playlist_track_in_result=False,
    lyrics_include='Love',
    lyrics_exclude='',
    lyrics_limit=30,
    limit=30,
)

print(q.collect())
