##################################################
from os.path import dirname, abspath, join  # noqa
import sys  # noqa

# Make sure we can import code from utils/
THIS_DIR = dirname(__file__)  # noqa
PROJ_DIR = abspath(join(THIS_DIR, '..'))  # noqa
sys.path.append(PROJ_DIR)  # noqa
##################################################

import polars as pl

from utils.pre_processing import process_song_pairings
from utils.search import PLAYLIST_DATA_FILE, PLAYLIST_TRACKS_DATA_FILE, TRACK_ADJACENT_DATA_FILE, SearchEngine

if len(sys.argv) >= 2:
    mode = sys.argv[1] or 'load'
else:
    mode = 'load'

if mode == 'write':
    process_song_pairings()
    print("Done.")

songs_df = pl.scan_parquet(TRACK_ADJACENT_DATA_FILE)
print(songs_df.collect())

search_engine = SearchEngine()
search_engine.load_data()

print(search_engine.find_related_songs(
    direction='prev',
    song_name='Josephine - Acoustic',
    artist_name='RITUAL',
)[1].collect())

print(search_engine.find_related_songs(
    direction='next',
    song_name='Josephine - Acoustic',
    artist_name='RITUAL',
)[1].collect())

print(search_engine.find_related_songs(
    direction='any',
    song_name='Josephine - Acoustic',
    artist_name='RITUAL',
)[1].collect())

print(search_engine.find_related_songs(
    direction='next',
    return_pairs=True,
)[1].collect())
