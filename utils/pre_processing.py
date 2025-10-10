"""Methods for pre-processing the data into more efficient formats at build time."""

import polars as pl

from utils.additional_data import actual_wcs_djs, queer_artists, poc_artists
from utils.playlist_classifiers import extract_dates_from_name
from utils.search_engine import (
    COUNTRY_DATA_FILE,
    PLAYLIST_DATA_FILE,
    PLAYLIST_TRACKS_DATA_FILE,
    TRACK_ADJACENT_DATA_FILE,
    TRACK_LYRICS_DATA_FILE,
    TRACK_DATA_FILE,
)

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


def write_to_parquet_file(data: pl.LazyFrame | pl.DataFrame, file_name: str):
    print(f'Writing {file_name}...')
    if isinstance(data, pl.DataFrame):
        data.write_parquet(file_name)
    else:
        data.sink_parquet(file_name)
    # TODO: Print file size of generated file


def process_playlist_and_song_data():
    source_data = pl.scan_parquet('data_playlists.parquet')
    bpm_data = pl.scan_parquet('data_song_bpm.parquet')

    playlists = source_data.select(
        pl.col('playlist_id').cast(PLAYLIST_ID_DTYPE).alias('playlist.id'),
        pl.col('name').alias('playlist.name'),
        pl.col('owner.id').cast(OWNER_ID_DTYPE),
        pl.col('owner.display_name').cast(
            OWNER_NAME_DTYPE).alias('owner.name'),
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
        pl.col('track.region').list.filter(
            ~pl.element().eq('')).cast(pl.List(pl.Categorical)),
        pl.col('track.country').list.filter(
            ~pl.element().eq('')).cast(pl.List(pl.Categorical)),
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
    write_to_parquet_file(playlists_extended, PLAYLIST_DATA_FILE)
    write_to_parquet_file(tracks_extended, TRACK_DATA_FILE)
    write_to_parquet_file(playlist_tracks, PLAYLIST_TRACKS_DATA_FILE)
    write_to_parquet_file(countries_df, COUNTRY_DATA_FILE)


def process_song_lyrics():
    """Process the song lyrics into a table sorted by track.id"""
    temp_file = 'temp_song_metadata_by_track_and_artist.parquet'

    print(f'Writing {temp_file}...')
    tracks = pl.scan_parquet(TRACK_DATA_FILE)\
        .select('track.id', 'track.name', 'track.artists.name')\
        .sort(['track.name', 'track.artists.name'])\
        .sink_parquet(temp_file)

    print(f'Reading {temp_file}...')
    tracks = pl.scan_parquet(temp_file)

    lyrics = pl.scan_parquet('song_lyrics.parquet')\
        .join(tracks,
              how='inner',
              left_on=['song', 'artist'],
              right_on=['track.name', 'track.artists.name'])\
        .select(pl.col('track.id'),
                pl.col('lyrics').alias('track.lyrics'))\
        .unique('track.id')\
        .sort('track.id')

    write_to_parquet_file(lyrics, TRACK_LYRICS_DATA_FILE)


def process_song_pairings():
    social_playlists = pl.scan_parquet(PLAYLIST_DATA_FILE)\
        .filter(pl.col('playlist.is_social_set'))\
        .filter(~pl.col('playlist.name').str.contains_any(['The Maine', 'delete', 'SPOTIFY']))\
        .select('playlist.id')

    songs_df = pl.scan_parquet(PLAYLIST_TRACKS_DATA_FILE)\
        .with_columns(pl.col('playlist_track.number').cast(pl.Int64))\
        .join(social_playlists, how='semi', on=['playlist.id'])\
        .sort('playlist.id', 'playlist_track.number')\
        .rolling(index_column='playlist_track.number', period='2i', group_by='playlist.id')\
        .agg(pl.col('track.id'))\
        .filter(pl.col('track.id').list.len().eq(2))\
        .group_by(pl.col('track.id'))\
        .agg(pl.col('playlist.id').n_unique().alias('playlist_count'))\
        .select(pl.col('track.id').list.get(0).alias('pair1.track.id'),
                pl.col('track.id').list.get(1).alias('pair2.track.id'),
                pl.col('playlist_count'))\
        .filter(~pl.col('pair1.track.id').eq(pl.col('pair2.track.id')))\
        .sort(['pair1.track.id', 'pair2.track.id'])
    # .sort('playlist_count', descending=True)

    # Write pre-processed data to parquet files
    write_to_parquet_file(songs_df, TRACK_ADJACENT_DATA_FILE)


def process_everything():
    """Runs all pre-processing in sequence."""
    # Initial run to split playlists, tracks and playlist entries
    process_playlist_and_song_data()

    # Song lyrics reuses the track data generated above
    process_song_lyrics()

    # Song pairings reuses the playlist entries data generated above
    process_song_pairings()
