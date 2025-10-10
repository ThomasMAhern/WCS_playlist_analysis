"""Methods for pre-processing the data into more efficient formats at build time."""

import polars as pl

from utils.additional_data import actual_wcs_djs, queer_artists, poc_artists
from utils.playlist_classifiers import extract_dates_from_name
from utils.search_engine import (
    COUNTRY_DATA_FILE,
    PLAYLIST_DATA_FILE,
    PLAYLIST_TRACKS_DATA_FILE,
    PLAYLIST_TRACKS_ORIGINAL_DATA_FILE,
    TRACK_ADJACENT_DATA_FILE,
    TRACK_CANONICAL_DATA_FILE,
    TRACK_DATA_FILE,
    TRACK_DUPLICATES_DATA_FILE,
    TRACK_LYRICS_DATA_FILE,
    TRACK_ORIGINAL_DATA_FILE,
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


def process_playlist_and_song_data(*, prepare_deduplication: bool = False):
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
        how='left', on=['track.name', 'track.artists.name']
    ).sort('track.id')

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
    write_to_parquet_file(countries_df, COUNTRY_DATA_FILE)
    write_to_parquet_file(playlists_extended, PLAYLIST_DATA_FILE)
    write_to_parquet_file(
        tracks_extended,
        TRACK_ORIGINAL_DATA_FILE if prepare_deduplication else TRACK_DATA_FILE)
    write_to_parquet_file(
        playlist_tracks,
        PLAYLIST_TRACKS_ORIGINAL_DATA_FILE if prepare_deduplication else PLAYLIST_TRACKS_DATA_FILE)


def process_song_duplicates(*, use_original_data: bool, print_statistics: bool = False):
    """Deduplicate songs based on track.name and track.artists.name."""

    # ===========================
    # Notes on song deduplication
    # ===========================
    #
    # Whereas Spotify considers the same song appearing on two different album
    # as two different tracks (with different track.id values),
    # we want to treat such instances only as a single track.
    #
    # =====================
    # Possible side effects
    # =====================
    #
    # --------------------------------
    # False Positives and/or Negatives
    # --------------------------------
    #
    # Due to data quality issues at Spotify's side, this will likely
    # still leave *some* songs that are effectively duplicates,
    # just with slightly different spellings of the title,
    # while maybe unifying some songs that are different recordings
    # which appear with the same name but on different albums.
    #
    # Most of these issues will likely mostly affect only older songs, though.
    #
    # NOTE: We could implement some safeguards, like checking for song length,
    #       once we have extended our data scraper to retrieve that data.
    #
    # ----------------------------------------
    # Unstable selection of canonical track.id
    # ----------------------------------------
    #
    # We also DO NOT currently implement an algorithm for deterministically
    # selecting one instance to be the "canonical" copy, but just use
    # the first one we stumble upon that has good metadata.
    #
    # This means that, within a single data preprocessing run, only
    # a single canonical track.id is selected for teach (name, artist)
    # pair, but which track.id is selected may vary between different runs.
    #
    # ==============
    # Other findings
    # ==============
    #
    # Within our dataset of (at that time) ~200,000 songs, a whopping ~86,000
    # were duplicates, that unified down to ~32,000 unique songs (plus the
    # ~114,000 songs that already had only a single copy).
    #
    # The most duplicated song had 22 duplicates, with others following closely behind.
    # Many duplicates were popular songs that were present in ~3,000 playlists each,
    # meaning that those duplicates definitely skewed the total statistics.
    #
    # There were ~75 songs with incomplete metdata that, on closer inspection,
    # seemed to not be songs but podcast episodes.

    songs_df = pl.scan_parquet(
        TRACK_ORIGINAL_DATA_FILE if use_original_data else TRACK_DATA_FILE)

    def is_non_empty(expr): return expr.is_not_null() & expr.ne('')
    has_track_name = is_non_empty(pl.col('track.name'))
    has_track_artist = is_non_empty(pl.col('track.artists.name'))

    songs_without_track_name_and_artist = songs_df\
        .filter(~has_track_name & ~has_track_artist)\
        .select('track.name', 'track.artists.name', 'track.id', 'playlist_count', 'dj_count')

    songs_without_track_name = songs_df\
        .filter(~has_track_name & has_track_artist)\
        .select('track.name', 'track.artists.name', 'track.id', 'playlist_count', 'dj_count')

    # NOTE: Based on a quick look, the songs without an artist all seem to be podcasts
    # TODO: Pre-filter playlists by removing podcasts (this information is exposed by the Spotify API)
    songs_without_track_artist = songs_df\
        .filter(~has_track_artist & has_track_name)\
        .select('track.name', 'track.artists.name', 'track.id', 'playlist_count', 'dj_count')

    duplicated_songs = songs_df\
        .filter(has_track_name & has_track_artist)\
        .group_by('track.name', 'track.artists.name')\
        .agg(pl.col('track.id'),
             pl.col('playlist_count').alias('playlist_count'),
             pl.col('dj_count'),
             pl.col('track.id').n_unique().alias('duplicate_count'),
             # This is only an estimate, because we would like playlists
             # which contain multiple different instances of the "same"
             # (by our definition) song to only be counted once.
             pl.col('playlist_count').sum().alias('estimated_total_playlist_count'))\
        .filter(pl.col('duplicate_count').gt(1))

    if print_statistics:
        print(songs_without_track_name_and_artist.collect(engine='streaming'))
        print(songs_without_track_name.collect(engine='streaming'))
        print(songs_without_track_artist.collect(engine='streaming'))

        print(duplicated_songs
              .sort('duplicate_count', descending=True)
              .collect(engine='streaming'))

        print(duplicated_songs
              .sort('estimated_total_playlist_count', descending=True)
              .collect(engine='streaming'))

        print(duplicated_songs.select(
            'duplicate_count').sum().collect(engine='streaming'))

    duplicate_to_canonical = duplicated_songs\
        .select(pl.col('track.id').list.drop_nulls())\
        .select(pl.col('track.id'),
                pl.col('track.id').list.first().alias('canonical.track.id'))\
        .explode('track.id')\
        .sort('track.id')

    if print_statistics:
        print(duplicate_to_canonical.collect(engine='streaming'))

    write_to_parquet_file(duplicated_songs.sort(
        ['track.name', 'track.artists.name']), TRACK_DUPLICATES_DATA_FILE)
    write_to_parquet_file(duplicate_to_canonical, TRACK_CANONICAL_DATA_FILE)


def deduplicate_playlist_and_song_data():
    """Replace all duplicate tracks with their canonical versions."""

    playlists = pl.scan_parquet(
        PLAYLIST_DATA_FILE)

    tracks_with_duplicates = pl.scan_parquet(
        TRACK_ORIGINAL_DATA_FILE)

    playlist_tracks_with_duplicates = pl.scan_parquet(
        PLAYLIST_TRACKS_ORIGINAL_DATA_FILE)

    duplicate_to_canonical = pl.scan_parquet(
        TRACK_CANONICAL_DATA_FILE)

    playlist_tracks = playlist_tracks_with_duplicates\
        .join(duplicate_to_canonical, how='left', on='track.id')\
        .with_columns(pl.col('track.id').alias('duplicate.track.id'))\
        .with_columns(pl.col('canonical.track.id').fill_null(pl.col('duplicate.track.id')).alias('track.id'))\
        .drop('canonical.track.id', 'duplicate.track.id')\
        .unique(['playlist.id', 'track.id', 'playlist_track.number'])\
        .sort('playlist.id', 'track.id', 'playlist_track.number')

    only_duplicates = duplicate_to_canonical\
        .filter(pl.col('track.id').ne(pl.col('canonical.track.id')))

    track_statistics = playlist_tracks\
        .join(playlists.select('playlist.id', 'owner.name'), how='inner', on='playlist.id')\
        .group_by('track.id').agg(
            pl.col('playlist.id').n_unique().alias('playlist_count'),
            pl.col('owner.name').n_unique().alias('dj_count'),
        )

    tracks = tracks_with_duplicates\
        .drop('playlist_count', 'dj_count')\
        .join(only_duplicates, how='anti', on='track.id')\
        .join(track_statistics, how='left', on='track.id')\
        .sort('track.id')

    write_to_parquet_file(tracks, TRACK_DATA_FILE)
    write_to_parquet_file(playlist_tracks, PLAYLIST_TRACKS_DATA_FILE)


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


def process_everything(merge_duplicates: bool = True):
    """Runs all pre-processing in sequence."""
    # Initial run to split playlists, tracks and playlist entries
    process_playlist_and_song_data(prepare_deduplication=merge_duplicates)

    # Duplicate song detection reuses the track data generated above
    process_song_duplicates(use_original_data=merge_duplicates)

    if merge_duplicates:
        deduplicate_playlist_and_song_data()

    # Song lyrics reuses the track data generated above
    process_song_lyrics()

    # Song pairings reuses the playlist entries data generated above
    process_song_pairings()
