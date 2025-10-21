import polars as pl
import sys

from utils.pre_processing import deduplicate_playlist_and_song_data, process_song_duplicates
from utils.search_engine import SearchEngine

if len(sys.argv) >= 2:
    mode = sys.argv[1] or 'load'
else:
    mode = 'load'

if mode == 'write':
    process_song_duplicates(use_original_data=True, print_statistics=True)
    deduplicate_playlist_and_song_data()
    print("Done.")

search_engine = SearchEngine()
search_engine.load_data()
