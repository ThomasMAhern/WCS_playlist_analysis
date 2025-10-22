##################################################
from os.path import dirname, abspath, join  # noqa
import sys  # noqa

# Make sure we can import code from utils/
THIS_DIR = dirname(__file__)  # noqa
PROJ_DIR = abspath(join(THIS_DIR, '..'))  # noqa
sys.path.append(PROJ_DIR)  # noqa
##################################################

import polars as pl

from utils.pre_processing import deduplicate_playlist_and_song_data, process_song_duplicates
from utils.search import SearchEngine

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
