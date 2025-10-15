from dataclasses import dataclass
from typing import Final, Literal

import polars as pl

from utils.search_engine.entity import Playlist, PlaylistTrack, Track, TrackAdjacent, TrackLyrics
from utils.search_engine.entity_base import PolarsLazyFrame
from utils.search_engine.filters import PlaylistSet, PlaylistTrackSet, TrackLyricsSet, TrackSet

DATA_DIR: Final = 'processed_data/'

PLAYLIST_DATA_FILE: Final = DATA_DIR + 'data_playlist_metadata.parquet'
PLAYLIST_ORIGINAL_DATA_FILE: Final = DATA_DIR + 'data_playlist_metadata.original.parquet'
PLAYLIST_TRACKS_DATA_FILE: Final = DATA_DIR + 'data_playlist_songs.parquet'
PLAYLIST_TRACKS_ORIGINAL_DATA_FILE: Final = DATA_DIR + 'data_playlist_songs.original.parquet'
TRACK_PLAYLISTS_DATA_FILE: Final = DATA_DIR + 'data_song_playlists.parquet'
TRACK_DATA_FILE: Final = DATA_DIR + 'data_song_metadata.parquet'
TRACK_ORIGINAL_DATA_FILE: Final = DATA_DIR + 'data_song_metadata.original.parquet'
TRACK_ADJACENT_DATA_FILE: Final = DATA_DIR + 'data_song_adjacent.parquet'
TRACK_LYRICS_DATA_FILE: Final = DATA_DIR + 'data_song_lyrics.parquet'
COUNTRY_DATA_FILE: Final = DATA_DIR + 'data_countries.parquet'

TRACK_DUPLICATES_DATA_FILE: Final = DATA_DIR + 'data_song_duplicates.parquet'
TRACK_CANONICAL_DATA_FILE: Final = DATA_DIR + 'data_song_canonical.parquet'


@dataclass(kw_only=True)
class CombinedData:
    """Holder for the different underlying data sources."""

    playlists: PolarsLazyFrame[Playlist]
    playlist_tracks: PolarsLazyFrame[PlaylistTrack]
    track_playlists: PolarsLazyFrame[PlaylistTrack]
    tracks: PolarsLazyFrame[Track]
    tracks_adjacent: PolarsLazyFrame[TrackAdjacent]
    track_lyrics: PolarsLazyFrame[TrackLyrics]
    countries: list[str]

    @property
    def all_playlists(self) -> PlaylistSet:
        return PlaylistSet(self.playlists, None, self.playlists, is_filtered=False)

    def all_playlist_tracks(self, sorted_column: Literal['track.id', 'playlist.id']) -> PlaylistTrackSet:
        if sorted_column == Playlist.id:
            return PlaylistTrackSet(self.playlist_tracks, is_filtered=False)
        elif sorted_column == Track.id:
            return PlaylistTrackSet(self.track_playlists, is_filtered=False)
        else:
            raise ValueError(f'Invalid sorted_column: {sorted_column}')

    @property
    def all_tracks(self) -> TrackSet:
        return TrackSet(self.tracks, is_filtered=False)

    @property
    def all_track_lyrics(self):
        return TrackLyricsSet(self.track_lyrics, is_filtered=False)

    @staticmethod
    def load_from_files():
        """Load the pre-generated data from the Parquet files."""
        return CombinedData(
            playlists=pl.scan_parquet(PLAYLIST_DATA_FILE),
            playlist_tracks=pl.scan_parquet(PLAYLIST_TRACKS_DATA_FILE),
            track_playlists=pl.scan_parquet(TRACK_PLAYLISTS_DATA_FILE),
            tracks=pl.scan_parquet(TRACK_DATA_FILE),
            tracks_adjacent=pl.scan_parquet(TRACK_ADJACENT_DATA_FILE),
            track_lyrics=pl.scan_parquet(TRACK_LYRICS_DATA_FILE),
            countries=pl.read_parquet(COUNTRY_DATA_FILE)['country'].to_list(),
        )
