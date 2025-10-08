import polars as pl
import sys

from utils.additional_data import actual_wcs_djs, queer_artists, poc_artists
from utils.playlist_classifiers import extract_dates_from_name
from utils.search_engine import COUNTRY_DATA_FILE, PLAYLIST_DATA_FILE, PLAYLIST_TRACKS_DATA_FILE, TRACK_DATA_FILE, SearchEngine

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
    ).sort('playlist.id').unique('playlist.id')

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
        playlists_extended.sink_parquet(PLAYLIST_DATA_FILE)

    tracks = source_data.select(
        pl.col('track.id').cast(TRACK_ID_DTYPE).alias('track.id'),
        pl.col('track.name').cast(TRACK_NAME_DTYPE),
        pl.col('track.artists.name').cast(TRACK_ARTIST_DTYPE),
        pl.col('track.album.release_date').cast(pl.Date),
    ).sort('track.id').unique()

    # Remove duplicated tracks (which can happen due to data quality issues)
    # and try to keep only a single copies with complete metadata.
    # TODO: This drops tracks where no copy with complete metadata exists
    track_info_columns = ['track.name',
                          'track.artists.name',
                          'track.album.release_date']

    all_track_ids = tracks.select('track.id')\
        .unique('track.id').sort('track.id')

    unique_tracks = tracks.filter(pl.all_horizontal(
        pl.col(track_info_columns).is_not_null())
    ).unique('track.id').join(all_track_ids, how='right', on='track.id')

    # Remove duplicated tracks (which can happen due to data quality issues)
    # and try to merge their metadata where possible
    # unique_tracks = tracks.select('track.id').unique()
    # for col in track_info_columns:
    #     unique_tracks = unique_tracks.join(
    #         tracks.select('track.id', col).filter(
    #             pl.col(col).is_not_null()).unique('track.id'),
    #         how='left', on=['track.id'])

    tracks_extended = unique_tracks.with_columns(
        pl.col('track.artists.name').str.to_lowercase().is_in(
            queer_artists).alias("track.artists.is_queer_artist"),
        pl.col('track.artists.name').str.to_lowercase().is_in(
            poc_artists).alias("track.artists.is_poc_artist"),
    ).join(
        bpm_data.select(
            pl.col('track.name').cast(TRACK_NAME_DTYPE),
            pl.col('track.artists.name').cast(TRACK_ARTIST_DTYPE),
            pl.col('bpm').cast(TRACK_BPM_DTYPE).alias('track.bpm')
        ).unique(['track.name', 'track.artists.name']),
        how='left', on=['track.name', 'track.artists.name'])

    # Write pre-processed track data to file
    if mode == 'write':
        tracks_extended.sink_parquet(TRACK_DATA_FILE)

    playlist_tracks = source_data.select(
        pl.col('playlist_id').cast(PLAYLIST_ID_DTYPE).alias('playlist.id'),
        pl.col('track.id').cast(TRACK_ID_DTYPE).alias('track.id'),
        # The following metadata is not strictly required
        pl.col('song_number').alias('playlist_track.number'),
        pl.col('added_at').alias('playlist_track.added_at'),
    ).sort('playlist.id', 'track.id', 'playlist_track.number')  # .unique('playlist.id', 'track.id')

    # Write pre-processed track <=> playlist membership data to file
    if mode == 'write':
        playlist_tracks.sink_parquet(PLAYLIST_TRACKS_DATA_FILE)

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

    # Write pre-processed country data to file
    if mode == 'write':
        countries_df.write_parquet(COUNTRY_DATA_FILE)

    search_engine = SearchEngine()
    search_engine.set_data(
        playlists=playlists_extended,
        playlist_tracks=playlist_tracks,
        tracks=tracks_extended,
        countries=countries_df,
    )


elif mode == 'load':
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
    playlist_include='',
    playlist_exclude='',
    # Result options
    skip_num_top_results=0,
)

result = q.unique().collect()
print(result)

# result.with_columns(pl.col('playlist.name').list.sort(
# ).list.join(',')).write_csv('output.csv')
# pl.scan_csv('output.csv').select('track.name', 'track.artists.name', 'track.id').sort(
#     'track.name', 'track.artists.name', 'track.id').sink_csv('output.processed.csv')
