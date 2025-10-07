import polars as pl
import sys

from utils.additional_data import actual_wcs_djs, queer_artists, poc_artists
from utils.playlist_classifiers import extract_dates_from_name

if len(sys.argv) >= 2:
    mode = sys.argv[1] or 'load'
else:
    mode = 'load'

TRACK_ID_DTYPE = pl.String
TRACK_BPM_DTYPE = pl.UInt8
TRACK_NAME_DTYPE = pl.String
TRACK_ARTIST_DTYPE = pl.String
PLAYLIST_ID_DTYPE = pl.String

# Handle different caching modes
if mode == 'live' or mode == 'write':
    # Calculate the derived data at runtime, and optionally write it to a file
    source_data = pl.scan_parquet('data_playlists.parquet')
    bpm_data = pl.scan_parquet('data_song_bpm.parquet')

    playlists = source_data.select(
        pl.col('playlist_id').alias('playlist.id'),
        pl.col('name').alias('playlist.name'),
        pl.col('owner.id'),
        pl.col('owner.display_name').alias('owner.name'),
        # Only required for extended data below
        pl.col('location').alias('playlist.location'),
    ).sort('playlist.id').unique()

    _is_social_set = (
        pl.col('playlist.extracted_date').list.len().gt(0)
        | pl.col('playlist.name').str.contains_any(['social', 'party', 'soir'], ascii_case_insensitive=True)
    )

    _is_wcs_dj = (
        pl.col('owner.id').str.contains_any(
            actual_wcs_djs, ascii_case_insensitive=True)
        | pl.col('owner.name').cast(pl.String).eq('Connie Wang')
        | pl.col('owner.name').cast(pl.String).eq('Koichi Tsunoda')
    )

    playlists_extended = playlists.with_columns(
        extract_dates_from_name(pl.col('playlist.name')).cast(
            pl.List(pl.Categorical)).alias('playlist.extracted_date'),
        pl.col('playlist.location').str.split(' - ').list.get(
            0, null_on_oob=True).cast(pl.Categorical).alias('playlist.region'),
        pl.col('playlist.location').str.split(' - ').list.get(
            1, null_on_oob=True).cast(pl.Categorical).alias('playlist.country'),
    ).with_columns(
        _is_social_set.alias('playlist.is_social_set'),
        _is_wcs_dj.alias('owner.is_wcs_dj'),
    ).drop('playlist.location')

    # Write pre-processed playlist data to file
    if mode == 'write':
        playlists_extended.sink_parquet('data_playlist_metadata.parquet')

    tracks = source_data.select(
        pl.col('track.id').cast(TRACK_ID_DTYPE).alias('track.id'),
        pl.col('track.name').cast(TRACK_NAME_DTYPE),
        pl.col('track.artists.name').cast(TRACK_ARTIST_DTYPE),
        pl.col('track.album.release_date').cast(pl.Date),
    ).sort('track.id').unique()

    tracks_extended = tracks.with_columns(
        pl.col('track.artists.name').str.to_lowercase().is_in(
            queer_artists).alias("track.artists.is_queer_artist"),
        pl.col('track.artists.name').str.to_lowercase().is_in(
            poc_artists).alias("track.artists.is_poc_artist"),
    ).join(
        bpm_data.select(
            pl.col('track.name').cast(TRACK_NAME_DTYPE),
            pl.col('track.artists.name').cast(TRACK_ARTIST_DTYPE),
            pl.col('bpm').cast(TRACK_BPM_DTYPE).alias('track.bpm')),
        how='left', on=['track.name', 'track.artists.name'])

    # Write pre-processed track data to file
    if mode == 'write':
        tracks_extended.sink_parquet('data_song_metadata.parquet')

    playlist_tracks = source_data.select(
        pl.col('playlist_id').cast(PLAYLIST_ID_DTYPE).alias('playlist.id'),
        pl.col('track.id').cast(TRACK_ID_DTYPE).alias('track.id'),
        # The following metadata is not strictly required
        pl.col('song_number').alias('playlist_track.number'),
        pl.col('added_at').alias('playlist_track.added_at'),
    ).sort('playlist.id', 'track.id', 'playlist_track.number').unique()

    # Write pre-processed track <=> playlist membership data to file
    if mode == 'write':
        playlist_tracks.sink_parquet('data_playlist_songs.parquet')

    countries_df = (
        playlists_extended.select(
            pl.col('playlist.country').alias('country').cast(pl.String))
        .unique()
        .drop_nulls()
        .sort('country')
        .collect(engine='streaming'))

    # Write pre-processed country data to file
    if mode == 'write':
        countries_df.write_parquet('data_countries.parquet')

elif mode == 'load':
    # Load the pre-generated data from the Parquet files
    playlists_extended = playlists = pl.scan_parquet(
        'data_playlist_metadata.parquet')
    playlist_tracks = pl.scan_parquet('data_playlist_songs.parquet')
    tracks_extended = tracks = pl.scan_parquet('data_song_metadata.parquet')
    countries_df = pl.read_parquet('data_countries.parquet')

countries = countries_df['country'].to_list()

#####################
# Filter parameters #
#####################

# Track-specific filters
song_input: str = ''
song_bpm_range: tuple[int, int] = (0, 150)
song_release_date: str = ''
artist_input: str = ''
queer_toggle: bool = False
poc_toggle: bool = True

song_inputs: list[str] = song_input.strip().lower().split(',')
song_release_dates: list[str] = song_release_date.strip().split(',')
artist_inputs: list[str] = artist_input.strip().lower().split(',')

# Playlist-specific filters
country_input: str = ''
dj_input: str = ''
playlist_input: str = ''
anti_playlist_input: str = ''

playlist_bpm_low: int = 90
playlist_bpm_med: int = 95
playlist_bpm_high: int = 100

dj_inputs: list[str] = dj_input.strip().lower().split(',')
playlist_inputs: list[str] = playlist_input.strip().lower().split(',')
anti_playlist_inputs: list[str] = anti_playlist_input.strip().lower().split(',')

# Playlist-membership specific filters
added_to_playlist_date_input: str = ''

added_to_playlist_date_inputs = added_to_playlist_date_input.strip().split(',')

# Result options
skip_num_top_results: int = 0

q = playlists_extended

print(q.limit(50).collect())
