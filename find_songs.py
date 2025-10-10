import polars as pl
import sys

from utils.pre_processing import process_playlist_and_song_data
from utils.search_engine import SearchEngine

if len(sys.argv) >= 2:
    mode = sys.argv[1] or 'load'
else:
    mode = 'load'

# Handle different caching modes
if mode == 'write':
    process_playlist_and_song_data()
    print("Done.")

search_engine = SearchEngine()
search_engine.load_data()

q = search_engine.find_songs(
    # Track-specific filters
    song_name='',
    song_bpm_range=(0, 150),
    song_release_date='',
    artist_name='',
    artist_is_queer=False,
    artist_is_poc=False,
    # Playlist-specific filters
    country='',
    dj_name='',
    playlist_include='late night',
    playlist_exclude='blues',
    # Playlist-membership specific filters
    added_to_playlist_date='',
    # Result options
    skip_num_top_results=0,
)

if mode == 'explain':
    print(q)
    print(q.explain(optimized=True))
else:
    result = q.unique().collect()
    print(result)

q = search_engine.find_playlists(
    # Track-specific filters
    song_name='',
    artist_name='Charlie Puth',
    # Playlist-specific filters
    playlist_include='late night',
    playlist_exclude='blues',
    # Result options
    limit=500,
)

if mode == 'explain':
    print(q)
    print(q.explain(optimized=True))
else:
    result = q.unique().collect()
    print(result)

# result.with_columns(pl.col('playlist.name').list.sort(
# ).list.join(',')).write_csv('output.csv')
# pl.scan_csv('output.csv').select('track.name', 'track.artists.name', 'track.id').sort(
#     'track.name', 'track.artists.name', 'track.id').sink_csv('output.processed.csv')

q = search_engine.find_songs(
    sort_by='playlist_count',
    descending=True,
    limit=100,
).with_row_index(offset=1)

if mode == 'explain':
    print(q)
    print(q.explain(optimized=True))
else:
    result = q.select('index', 'playlist_count', 'track.name').collect()
    print(result)
