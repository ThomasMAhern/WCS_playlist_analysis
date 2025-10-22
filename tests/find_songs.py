##################################################
from os.path import dirname, abspath, join  # noqa
import sys  # noqa

# Make sure we can import code from utils/
THIS_DIR = dirname(__file__)  # noqa
PROJ_DIR = abspath(join(THIS_DIR, '..'))  # noqa
sys.path.append(PROJ_DIR)  # noqa
##################################################

import polars as pl
import polars.selectors as cs

from utils.common.columns import pull_columns_to_front
from utils.pre_processing import process_playlist_and_song_data
from utils.search_engine import SearchEngine
from utils.search_engine.entity import Playlist, PlaylistOwner, PlaylistTrack, Track

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

print(q.collect(engine='streaming'))

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

print(q.collect(engine='streaming'))

q = search_engine\
    .find_songs(
        sort_by='playlist_count',
        descending=True,
        limit=100
    )\
    .rename({'track.country': 'country'})\
    .drop('track.region')\
    .select((cs.all()
             - Playlist.matching_columns()
             - PlaylistTrack.matching_columns()
             - PlaylistOwner.matching_columns())
            | cs.by_name('playlist.name')
            | cs.by_name('owner.name'))\
    .select(pull_columns_to_front(
        'track.name',
        'track.url',
        'playlist_count',
        'dj_count',
        'track.bpm',
        'track.artists.is_queer_artist',
        'track.artists.is_poc_artist',
        'playlist.name',
        'track.artists',
        'owner.name',
        'country',
    ))\
    .with_row_index(offset=1)

print(q.collect(engine='streaming'))

q = search_engine\
    .find_songs(
        artist_is_queer=True,
        sort_by='playlist_count',
        descending=True,
        limit=100
    )\
    .rename({'track.country': 'country'})\
    .drop('track.region')\
    .select((cs.all()
             - Playlist.matching_columns()
             - PlaylistTrack.matching_columns()
             - PlaylistOwner.matching_columns())
            | cs.by_name('playlist.name')
            | cs.by_name('owner.name'))\
    .select(pull_columns_to_front(
        'track.name',
        'track.url',
        'playlist_count',
        'dj_count',
        'track.bpm',
        'track.artists.is_queer_artist',
        'track.artists.is_poc_artist',
        'playlist.name',
        'track.artists',
        'owner.name',
        'country',
    ))\
    .with_row_index(offset=1)

print(q.collect(engine='streaming'))

q = search_engine\
    .find_songs(
        playlist_include='late night',
        playlist_exclude='blues',
        sort_by=[
            'hit_count',
            'matching_playlist_count',
            'playlist_count',
            'dj_count'
        ],
        descending=True,
        limit=100
    )\
    .rename({'track.country': 'country'})\
    .drop('track.region')\
    .select((cs.all()
             - Playlist.matching_columns()
             - PlaylistTrack.matching_columns()
             - PlaylistOwner.matching_columns())
            | cs.by_name('playlist.name')
            | cs.by_name('owner.name'))\
    .select(pull_columns_to_front(
        'track.name',
        'track.url',
        'playlist_count',
        'dj_count',
        'hit_terms',
        'track.bpm',
        'matching_playlist_count',
        'track.artists.is_queer_artist',
        'track.artists.is_poc_artist',
        'playlist.name',
        'track.artists',
        'owner.name',
        'country',
    ))\
    .with_row_index(offset=1)

print(q.collect(engine='streaming'))
