import polars as pl
import sys

from utils.additional_data import actual_wcs_djs, queer_artists, poc_artists
from utils.playlist_classifiers import extract_dates_from_name
from utils.search_engine import COUNTRY_DATA_FILE, PLAYLIST_DATA_FILE, PLAYLIST_TRACKS_DATA_FILE, TRACK_DATA_FILE, SearchEngine

if len(sys.argv) >= 2:
    mode = sys.argv[1] or 'load'
else:
    mode = 'load'

# NOTE: Setting TRACK_ID_DTYPE and PLAYLIST_ID_DTYPE to pl.Categorical
#       instead of pl.String blows up the size of data_playlist_songs.parquet
#       by a factor of more than 4x (227 MB vs. 41 MB), so it seems
#       like pl.String is the only right answer here.

TRACK_ID_DTYPE = pl.String
TRACK_BPM_DTYPE = pl.UInt8
TRACK_NAME_DTYPE = pl.String
TRACK_ARTIST_DTYPE = pl.String
PLAYLIST_ID_DTYPE = pl.String
OWNER_ID_DTYPE = pl.String
OWNER_NAME_DTYPE = pl.String

# Handle different caching modes
if mode == 'write':
    # Calculate the derived data at runtime, and optionally write it to a file
    source_data = pl.scan_parquet('data_playlists.parquet')
    bpm_data = pl.scan_parquet('data_song_bpm.parquet')

    playlists = source_data.select(
        pl.col('playlist_id').cast(PLAYLIST_ID_DTYPE).alias('playlist.id'),
        pl.col('name').alias('playlist.name'),
        pl.col('owner.id').cast(OWNER_ID_DTYPE),
        pl.col('owner.display_name').cast(OWNER_NAME_DTYPE).alias('owner.name'),
        # Only required for extended data below
        pl.col('location').alias('playlist.location'),
    ).sort('playlist.id').unique('playlist.id')

    _is_social_set = (
        pl.col('playlist.extracted_date').list.len().gt(0)
        | pl.col('playlist.name').str.contains_any(['social', 'party', 'soir'], ascii_case_insensitive=True)
    )

    _is_wcs_dj = (
        pl.col('owner.id').cast(pl.String).str.contains_any(
            actual_wcs_djs, ascii_case_insensitive=True)
        | pl.col('owner.name').cast(pl.String).eq('Connie Wang')
        | pl.col('owner.name').cast(pl.String).eq('Koichi Tsunoda')
    )

    playlists_extended = playlists.with_columns(
        extract_dates_from_name(pl.col('playlist.name')).cast(
            pl.List(pl.String)).alias('playlist.extracted_date'),
        pl.col('playlist.location').str.split(' - ').list.get(
            0, null_on_oob=True).cast(pl.Categorical).alias('playlist.region'),
        pl.col('playlist.location').str.split(' - ').list.get(
            1, null_on_oob=True).cast(pl.Categorical).alias('playlist.country'),
    ).with_columns(
        _is_social_set.alias('playlist.is_social_set'),
        _is_wcs_dj.alias('owner.is_wcs_dj'),
    ).drop('playlist.location')

    tracks = source_data.select(
        pl.col('track.id').cast(TRACK_ID_DTYPE).alias('track.id'),
        pl.col('track.name').cast(TRACK_NAME_DTYPE),
        pl.col('track.artists.name').cast(TRACK_ARTIST_DTYPE),
        pl.col('track.album.release_date').cast(pl.Date),
        pl.col('location').str.split(' - ').list.get(
            0, null_on_oob=True).cast(pl.Categorical).alias('track.region'),
        pl.col('location').str.split(' - ').list.get(
            1, null_on_oob=True).cast(pl.Categorical).alias('track.country'),
        pl.col('playlist_id').alias('playlist.id'),
        pl.col('owner.display_name').alias('owner.name'),
    ).group_by('track.id').agg(
        pl.col('track.name').drop_nulls().first(),
        pl.col('track.artists.name').drop_nulls()
        .unique().alias('track.artists'),
        pl.col('track.album.release_date').drop_nulls().first(),
        pl.col('track.region').drop_nulls().sort().unique(),
        pl.col('track.country').drop_nulls().sort().unique(),
        pl.col('playlist.id').n_unique().alias('playlist_count'),
        pl.col('owner.name').n_unique().alias('dj_count'),
    ).with_columns(
        pl.col('track.album.release_date').cast(pl.Date),
        pl.col('track.region').list.filter(~pl.element().eq('')).cast(pl.List(pl.Categorical)),
        pl.col('track.country').list.filter(~pl.element().eq('')).cast(pl.List(pl.Categorical)),
    ).sort('track.id').unique()

    tracks_extended = tracks.with_columns(
        pl.col('track.artists').list.join(', ').alias('track.artists.name'),
        pl.col('track.artists').list.eval(pl.element().str.to_lowercase().is_in(
            queer_artists)).list.any().alias("track.artists.is_queer_artist"),
        pl.col('track.artists').list.eval(pl.element().str.to_lowercase().is_in(
            poc_artists)).list.any().alias("track.artists.is_poc_artist"),
    ).join(
        bpm_data.select(
            pl.col('track.name').cast(TRACK_NAME_DTYPE),
            pl.col('track.artists.name').cast(TRACK_ARTIST_DTYPE),
            pl.col('bpm').cast(TRACK_BPM_DTYPE).alias('track.bpm')
        ).unique(['track.name', 'track.artists.name']),
        how='left', on=['track.name', 'track.artists.name']).sort('track.id')

    playlist_tracks = source_data.select(
        pl.col('playlist_id').cast(PLAYLIST_ID_DTYPE).alias('playlist.id'),
        pl.col('track.id').cast(TRACK_ID_DTYPE).alias('track.id'),
        # The following metadata is not strictly required
        pl.col('song_number').cast(pl.UInt16).alias('playlist_track.number'),
        pl.col('added_at').cast(pl.Date).alias('playlist_track.added_at'),
    ).filter(
        pl.col('playlist.id').is_not_null(),
        pl.col('track.id').is_not_null(),
    ).unique(['playlist.id', 'track.id', 'playlist_track.number'])\
    .sort('playlist.id', 'track.id', 'playlist_track.number')

    # # Write pre-processed track <=> playlist membership data
    # # optimized for track => playlist lookup
    #     playlist_tracks = source_data.select(
    #     pl.col('playlist_id').cast(PLAYLIST_ID_DTYPE).alias('playlist.id'),
    #     pl.col('track.id').cast(TRACK_ID_DTYPE).alias('track.id'),
    #     # The following metadata is not strictly required
    #     pl.col('song_number').alias('playlist_track.number'),
    #     pl.col('added_at').alias('playlist_track.added_at'),
    # ).sort('playlist.id', 'track.id', 'playlist_track.number').unique()

    countries_df = (
        playlists_extended.select(
            pl.col('playlist.country').alias('country').cast(pl.String))
        .unique()
        .drop_nulls()
        .sort('country')
        .collect(engine='streaming'))

    # Write pre-processed data to parquet files
    print(f'Writing {PLAYLIST_DATA_FILE}...')
    playlists_extended.sink_parquet(PLAYLIST_DATA_FILE)

    print(f'Writing {TRACK_DATA_FILE}...')
    tracks_extended.sink_parquet(TRACK_DATA_FILE)

    print(f'Writing {PLAYLIST_TRACKS_DATA_FILE}...')
    playlist_tracks.sink_parquet(PLAYLIST_TRACKS_DATA_FILE)

    print(f'Writing {COUNTRY_DATA_FILE}...')
    countries_df.write_parquet(COUNTRY_DATA_FILE)

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

result = q.unique().collect()
print(result)

# result.with_columns(pl.col('playlist.name').list.sort(
# ).list.join(',')).write_csv('output.csv')
# pl.scan_csv('output.csv').select('track.name', 'track.artists.name', 'track.id').sort(
#     'track.name', 'track.artists.name', 'track.id').sink_csv('output.processed.csv')
