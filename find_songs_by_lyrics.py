import polars as pl
import sys

from utils.pre_processing import process_song_lyrics
from utils.search_engine import SearchEngine

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
