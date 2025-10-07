import polars as pl
import polars.selectors as cs
import sys

from utils.additional_data import actual_wcs_djs, queer_artists, poc_artists
from utils.playlist_classifiers import extract_dates_from_name

if len(sys.argv) >= 2:
    mode = sys.argv[1] or 'load'
else:
    mode = 'load'

# Handle different caching modes
if mode == 'live' or mode == 'write':
    # Calculate the derived data at runtime, and optionally write it to a file
    source_data = pl.scan_parquet('data_playlists.parquet')

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
            0, null_on_oob=True).alias('playlist.region'),
        pl.col('playlist.location').str.split(' - ').list.get(
            1, null_on_oob=True).alias('playlist.country'),
    ).with_columns(
        _is_social_set.alias('playlist.is_social_set'),
        _is_wcs_dj.alias('owner.is_wcs_dj'),
    ).select(cs.all() - cs.by_name('playlist.location'))

    # Write pre-processed playlist data to file
    if mode == 'write':
        playlists_extended.collect().write_parquet('data_playlist_metadata.parquet')

    tracks = source_data.select(
        pl.col('track.id').alias('track.id'),
        pl.col('track.name'),
        pl.col('track.artists.name'),
        pl.col('track.album.release_date'),
    ).sort('track.id').unique()

    tracks_extended = tracks.with_columns(
        pl.col('track.artists.name').str.to_lowercase().is_in(
            queer_artists).alias("track.artists.is_queer_artist"),
        pl.col('track.artists.name').str.to_lowercase().is_in(
            poc_artists).alias("track.artists.is_poc_artist"),
    )

    # Write pre-processed track data to file
    if mode == 'write':
        tracks_extended.collect().write_parquet('data_song_metadata.parquet')

    playlist_tracks = source_data.select(
        pl.col('playlist_id').alias('playlist.id'),
        pl.col('track.id').alias('track.id'),
        # The following metadata is not strictly required
        pl.col('song_number').alias('playlist_track.number'),
        pl.col('added_at').alias('playlist_track.added_at'),
    ).sort('playlist_id', 'track_id', 'song_number').unique()

    # Write pre-processed track <=> playlist membership data to file
    if mode == 'write':
        tracks.collect().write_parquet('data_playlist_songs.parquet')

elif mode == 'load':
    # Load the pre-generated data from the Parquet files
    playlists_extended = playlists = pl.scan_parquet(
        'data_playlist_metadata.parquet')
    playlist_tracks = pl.scan_parquet('data_playlist_songs.parquet')
    tracks_extended = tracks = pl.scan_parquet('data_song_metadata.parquet')

q = playlists_extended

print(q.limit(50).collect())
