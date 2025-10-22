##################################################
from os.path import dirname, abspath, join  # noqa
import sys  # noqa

# Make sure we can import code from utils/
THIS_DIR = dirname(__file__)  # noqa
PROJ_DIR = abspath(join(THIS_DIR, '..'))  # noqa
sys.path.append(PROJ_DIR)  # noqa
##################################################

import polars as pl

from utils.pre_processing import process_song_lyrics
from utils.search import SearchEngine

if len(sys.argv) >= 2:
    mode = sys.argv[1] or 'load'
else:
    mode = 'load'

if mode == 'write':
    process_song_lyrics()
    print("Done.")

search_engine = SearchEngine()
search_engine.load_data()

q = search_engine.find_songs(
    song_name='Back',
    artist_name='',
    playlist_in_result=False,
    playlist_track_in_result=False,
    lyrics_include='Love',
    lyrics_exclude='',
    lyrics_in_result=True,
    sort_by='matched_lyrics_count',
    limit=30,
)

print(q.collect())
