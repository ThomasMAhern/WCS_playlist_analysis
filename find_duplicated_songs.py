import polars as pl
import sys

from utils.pre_processing import process_song_duplicates
from utils.search_engine import SearchEngine

if len(sys.argv) >= 2:
    mode = sys.argv[1] or 'load'
else:
    mode = 'load'

if mode == 'write':
    process_song_duplicates()
    print("Done.")

search_engine = SearchEngine()
search_engine.load_data()
