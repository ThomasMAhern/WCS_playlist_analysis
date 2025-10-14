from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, overload

import polars as pl
import polars.selectors as cs

from utils.search_engine.entity import TrackLyrics, Playlist, PlaylistTrack, Track, TrackAdjacent
from utils.search_engine.entity_base import PolarsLazyFrame
from utils.search_utils.filters import create_date_filter, create_text_filter, or_filter
from utils.search_utils.stats import count_n_unique

PLAYLIST_DATA_FILE = 'data_playlist_metadata.parquet'
PLAYLIST_TRACKS_DATA_FILE = 'data_playlist_songs.parquet'
PLAYLIST_TRACKS_ORIGINAL_DATA_FILE = 'data_playlist_songs.original.parquet'
TRACK_DATA_FILE = 'data_song_metadata.parquet'
TRACK_ORIGINAL_DATA_FILE = 'data_song_metadata.original.parquet'
TRACK_ADJACENT_DATA_FILE = 'data_song_adjacent.parquet'
TRACK_LYRICS_DATA_FILE = 'data_song_lyrics.parquet'
COUNTRY_DATA_FILE = 'data_countries.parquet'

TRACK_DUPLICATES_DATA_FILE = 'data_song_duplicates.parquet'
TRACK_CANONICAL_DATA_FILE = 'data_song_canonical.parquet'


def extract_countries(countries_dataframe: pl.DataFrame) -> list[str]:
    return countries_dataframe['country'].to_list()


class FilteredBy(StrEnum):
    Playlist = 'playlist'
    PlaylistTrack = 'playlist_track'
    Track = 'track'
    Lyrics = 'lyrics'


@dataclass(slots=True)
class PlaylistSet:
    """A collection of playlists. Each `playlist.id` should appear at most once within each collection."""
    included_playlists: PolarsLazyFrame[Playlist]
    excluded_playlists: PolarsLazyFrame[Playlist] | None
    all_playlists: PolarsLazyFrame[Playlist]
    is_filtered: bool

    def with_playlist_url(self):
        return PlaylistSet(
            included_playlists=self.included_playlists.with_columns(
                pl.when(pl.col('playlist.id').is_not_null()).then(pl.concat_str(
                    pl.lit('https://open.spotify.com/track/'), 'playlist.id')).alias('playlist.url')),
            excluded_playlists=self.excluded_playlists,
            all_playlists=self.all_playlists,
            is_filtered=self.is_filtered)

    def with_owner_url(self):
        return PlaylistSet(
            included_playlists=self.included_playlists.with_columns(
                pl.when(pl.col('owner.id').is_not_null()).then(pl.concat_str(
                    pl.lit('https://open.spotify.com/user/'), 'owner.id')).alias('owner.url')),
            excluded_playlists=self.excluded_playlists,
            all_playlists=self.all_playlists,
            is_filtered=self.is_filtered)

    def with_extra_columns(self):
        return self\
            .with_playlist_url()\
            .with_owner_url()

    def filter_playlist_tracks(self, playlist_tracks_to_filter: PlaylistTrackSet, include_playlist_info: bool = True) -> PlaylistTrackSet:
        """Filter the specified playlist_tracks_to_filter to only include tracks from matched playlists."""

        if not self.is_filtered and not include_playlist_info:
            return playlist_tracks_to_filter

        matching_playlist_tracks = self.included_playlists.join(
            playlist_tracks_to_filter.playlist_tracks,
            how='inner' if include_playlist_info else 'semi',
            on=['playlist.id'])

        if self.excluded_playlists is not None:
            excluded_playlist_tracks = self.excluded_playlists.join(
                playlist_tracks_to_filter.playlist_tracks, how='inner', on=['playlist.id'])

            matching_playlist_tracks = matching_playlist_tracks.join(
                excluded_playlist_tracks, how='anti', on=['track.id'])

        return PlaylistTrackSet(matching_playlist_tracks,
                                is_filtered=self.is_filtered or playlist_tracks_to_filter.is_filtered)

    def filter_tracks(self, playlist_tracks_to_filter: PlaylistTrackSet, tracks_to_filter: TrackSet) -> TrackSet:
        """Filter the specified tracks_to_filter to only include tracks from matched playlists."""
        matching_playlist_tracks =\
            self.filter_playlist_tracks(
                playlist_tracks_to_filter)

        matching_tracks =\
            matching_playlist_tracks.filter_tracks(
                tracks_to_filter,
                include_playlist_track_info=True)

        return matching_tracks


@dataclass(slots=True)
class PlaylistFilter:
    """Playlist-specific filters."""

    # User-provided parameters
    country: str | list[str] = ''
    dj_name: str = ''
    dj_name_exclude: str = ''
    playlist_include: str = ''
    playlist_exclude: str = ''

    # Parsed filters
    match_country: pl.Expr = field(init=False)
    match_dj_name: pl.Expr = field(init=False)
    match_dj_name_exclude: pl.Expr = field(init=False)
    match_playlist: pl.Expr = field(init=False)
    match_excluded_playlist: pl.Expr = field(init=False)

    def __post_init__(self):
        """Parses the user-provided filter specifications."""
        self.match_dj_name = or_filter(
            create_text_filter(self.dj_name,
                               pl.col('owner.name')),
            create_text_filter(self.dj_name,
                               pl.col('owner.id')))

        self.match_dj_name_exclude = or_filter(
            create_text_filter(self.dj_name_exclude,
                               pl.col('owner.name')),
            create_text_filter(self.dj_name_exclude,
                               pl.col('owner.id')))

        self.match_country =\
            create_text_filter(self.country,
                               pl.col('playlist.country'))

        self.match_playlist =\
            create_text_filter(self.playlist_include,
                               pl.col('playlist.name'))

        self.match_excluded_playlist =\
            create_text_filter(self.playlist_exclude,
                               pl.col('playlist.name'))

    @property
    def has_filters(self) -> bool:
        """Returns whether any playlist filters are defined."""
        return self.match_dj_name is not None\
            or self.match_dj_name_exclude is not None\
            or self.match_country is not None\
            or self.match_playlist is not None\
            or self.match_excluded_playlist is not None

    def filter_playlists(self, playlists_to_filter: PlaylistSet) -> PlaylistSet:
        """Filter the specified playlists_to_filter to only include playlists matching this filter."""
        matching_playlists = playlists_to_filter.included_playlists

        if self.match_playlist is not None:
            matching_playlists = matching_playlists.filter(
                self.match_playlist)

        # Courtesy of Franzi M. (for the country filter suggestion)
        if self.match_country is not None:
            matching_playlists = matching_playlists.filter(
                self.match_country)

        if self.match_dj_name is not None:
            matching_playlists = matching_playlists.filter(
                self.match_dj_name)

        if self.match_dj_name_exclude is not None:
            matching_playlists = matching_playlists.filter(
                ~self.match_dj_name_exclude)

        # Courtesy of Tobias N. (for the suggestion of the playlist_exclude filter)
        excluded_playlists: pl.LazyFrame | None

        if self.match_excluded_playlist is not None:
            anti_predicate = self.match_excluded_playlist

            # We want to remove tracks that are in these excluded playlists
            # from the result, even when they are present in other matching playlists
            excluded_playlists = playlists_to_filter.all_playlists.filter(anti_predicate)\
                .select('playlist.id')

            # But as an optimization, we also want to avoid including those playlists in the first place.
            matching_playlists = matching_playlists.filter(
                anti_predicate.not_())

            # Also keep the list of playlists to exclude from before
            if playlists_to_filter.excluded_playlists is not None:
                excluded_playlists = pl.concat([
                    excluded_playlists,
                    playlists_to_filter.excluded_playlists,
                ]).unique(['playlist.id'])
        else:
            excluded_playlists = playlists_to_filter.excluded_playlists

        # # Remove everything but the strictly necessary information
        # matching_playlists = matching_playlists.select('playlist.id')

        return PlaylistSet(
            included_playlists=matching_playlists,
            excluded_playlists=excluded_playlists,
            all_playlists=playlists_to_filter.all_playlists,
            is_filtered=self.has_filters,
        )


@dataclass(slots=True)
class PlaylistTrackSet:
    """A collection of playlist-to-track relations."""
    playlist_tracks: PolarsLazyFrame[PlaylistTrack] # PlaylistTrackWithPlaylist
    is_filtered: bool

    def filter_playlists(self, playlists_to_filter: PlaylistSet) -> PlaylistSet:
        """Filter the specified playlists to only include playlists mentioned in this set."""

        if not self.is_filtered:
            return playlists_to_filter

        matching_playlists = playlists_to_filter.included_playlists.join(
            self.playlist_tracks,
            how='semi',
            on=['playlist.id'])

        return PlaylistSet(
            included_playlists=matching_playlists,
            excluded_playlists=playlists_to_filter.excluded_playlists,
            all_playlists=playlists_to_filter.all_playlists,
            is_filtered=self.is_filtered or playlists_to_filter.is_filtered,
        )

    def filter_tracks(
        self,
        tracks_to_filter: TrackSet,
        *,
        include_playlist_info: bool = True,
        include_playlist_track_info: bool = True
    ) -> TrackSet:
        """Filter the specified tracks to only include tracks from playlists in this set."""

        if not self.is_filtered and not include_playlist_info and not include_playlist_track_info:
            # return tracks_to_filter
            return TrackSet(
                tracks_to_filter.tracks,
                is_filtered=tracks_to_filter.is_filtered,
            )

        if include_playlist_info or include_playlist_track_info:
            columns_to_select = cs.empty()

            if include_playlist_info:
                columns_to_select |= cs.starts_with("playlist.")
                columns_to_select |= cs.starts_with("owner.")

            if include_playlist_track_info:
                columns_to_select |= cs.starts_with("playlist_track.")

            matching_playlist_tracks = self.playlist_tracks\
                .group_by('track.id')\
                .agg(columns_to_select)
        else:
            matching_playlist_tracks = self.playlist_tracks

        matching_tracks = tracks_to_filter.tracks.join(
            matching_playlist_tracks,
            how='inner' if include_playlist_info or include_playlist_track_info else 'semi',
            on=['track.id'])

        return TrackSet(
            matching_tracks,
            is_filtered=self.is_filtered or tracks_to_filter.is_filtered,
        )


@dataclass(slots=True)
class PlaylistTrackFilter:
    """Playlist-membership-specific filters."""

    # User-provided parameters
    added_to_playlist_date: str = ''

    # Parsed filters
    match_added_to_playlist_date: pl.Expr = field(init=False)

    def __post_init__(self):
        """Parses the user-provided filter specifications."""
        self.match_added_to_playlist_date =\
            create_date_filter(self.added_to_playlist_date,
                               pl.col('playlist_track.added_at'))

    @property
    def has_filters(self) -> bool:
        """Returns whether any playlist_track filters are defined."""
        return self.match_added_to_playlist_date is not None

    def filter_playlist_tracks(self, playlist_tracks_to_filter: PlaylistTrackSet) -> PlaylistTrackSet:
        """Filter the specified playlist_tracks_to_filter to only include playlist_tracks matching this filter."""
        matching_playlist_tracks = playlist_tracks_to_filter.playlist_tracks

        # Courtesy of Franzi M. (for the added_to_playlist_date filter suggestion)
        if self.match_added_to_playlist_date is not None:
            matching_playlist_tracks = matching_playlist_tracks.filter(
                self.match_added_to_playlist_date)

        # Remove everything but the strictly necessary information
        matching_playlist_tracks = matching_playlist_tracks\
            .group_by('track.id')\
            .agg(cs.by_name('playlist.id', 'playlist.name',
                            'owner.id', 'owner.name',
                            require_all=False)
                 .unique().sort())

        return PlaylistTrackSet(
            matching_playlist_tracks,
            is_filtered=self.has_filters or playlist_tracks_to_filter.is_filtered
        )


@dataclass(slots=True)
class TrackSet:
    """A collection of tracks. Each `track.id` should appear at most once with each collection."""
    tracks: PolarsLazyFrame[Track] # TrackWithPlaylist
    is_filtered: bool

    def with_extra_columns(self):
        return TrackSet(self.tracks.with_columns(
            pl.col('track.bpm').fill_null(0.0),
            pl.when(pl.col('track.id').is_not_null()).then(pl.concat_str(
                pl.lit('https://open.spotify.com/track/'), 'track.id')).alias('track.url'),
        ), is_filtered=self.is_filtered)

    def sort_by(self, by, *more_by, descending: bool):
        return TrackSet(
            self.tracks.sort(by, *more_by, descending=descending),
            is_filtered=self.is_filtered,
        ) if by is not None else self

    def filter_lyrics(self, lyrics_to_filter: TrackLyricsSet) -> TrackLyricsSet:
        if not self.is_filtered:
            return TrackLyricsSet(
                lyrics_to_filter,
                is_filtered=lyrics_to_filter.is_filtered)
        else:
            return TrackLyricsSet(
                lyrics_to_filter.track_lyrics.join(
                    self.tracks,
                    how='semi',
                    on='track.id'),
                is_filtered=True)

    def filter_playlist_tracks(self, playlist_tracks_to_filter: PlaylistTrackSet, *, include_track_info: bool = True) -> PlaylistTrackSet:
        # Skip join if it would be a no-op anyway
        if not self.is_filtered:
            return playlist_tracks_to_filter

        # TODO: Benchmark which implementation is faster, remove the other one
        #       If both are comparable, remove the more complicated second version
        use_first_impl = True

        if use_first_impl:
            matching_playlist_tracks = playlist_tracks_to_filter.playlist_tracks.join(
                self.tracks,
                how='inner' if include_track_info else 'semi',
                on='track.id')
        else:
            matching_tracks = self.tracks

            if not include_track_info:
                matching_tracks = matching_tracks.select('track.id')

            matching_playlist_tracks = matching_tracks.join(
                playlist_tracks_to_filter.playlist_tracks,
                how='inner',
                on=['track.id'])

        return PlaylistTrackSet(
            matching_playlist_tracks,
            is_filtered=True,
        )

    def filter_playlists(self, playlist_tracks_to_filter: PlaylistTrackSet, playlists_to_filter: PlaylistSet) -> PlaylistSet:
        """Filter the specified playlists_to_filter to only include playlists that contain at least one track from this set."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered:
            return playlists_to_filter

        matching_playlists = playlists_to_filter.included_playlists.join(
            playlist_tracks_to_filter.playlist_tracks.join(
                self.tracks, how='semi', on=['track.id']),
            how='semi', on=['playlist.id'])

        return PlaylistSet(
            matching_playlists,
            playlists_to_filter.excluded_playlists,
            playlists_to_filter.all_playlists,
            is_filtered=True,
        )


@dataclass(slots=True)
class TrackFilter:
    """"Track-specific filters."""

    # User-provided parameters
    song_name: str = ''
    song_bpm_range: tuple[int, int] | None = None
    song_release_date: str = ''
    artist_name: str = ''
    artist_is_queer: bool = False
    artist_is_poc: bool = False

    # Parsed filters
    match_song_name: pl.Expr = field(init=False)
    match_song_release_date: pl.Expr = field(init=False)
    match_artist_name: pl.Expr = field(init=False)

    def __post_init__(self):
        """Parses the user-provided filter specifications."""
        self.match_song_name =\
            create_text_filter(self.song_name,
                               pl.col('track.name'))
        self.match_song_release_date =\
            create_date_filter(self.song_release_date,
                               pl.col('track.album.release_date'))
        self.match_artist_name =\
            create_text_filter(self.artist_name,
                               pl.col('track.artists.name'))

    @property
    def has_filters(self) -> bool:
        """Returns whether any track filters are defined."""
        return self.match_song_name is not None\
            or self.song_bpm_range is not None\
            or self.match_song_release_date is not None\
            or self.match_artist_name is not None\
            or self.artist_is_queer\
            or self.artist_is_poc

    def filter_tracks(self, tracks_to_filter: TrackSet) -> TrackSet:
        """Filter the specified tracks_to_filter to only include tracks matching this filter."""

        # Apply filters to provided data
        matching_tracks = tracks_to_filter.tracks

        if self.match_song_name is not None:
            matching_tracks = matching_tracks.filter(
                self.match_song_name)

        if self.match_artist_name is not None:
            matching_tracks = matching_tracks.filter(
                self.match_artist_name)

        if self.artist_is_queer:
            matching_tracks = matching_tracks.filter(
                pl.col('track.artists.is_queer_artist'))

        if self.artist_is_poc:
            matching_tracks = matching_tracks.filter(
                pl.col('track.artists.is_poc_artist'))

        if self.song_bpm_range:
            matching_tracks = matching_tracks.filter(
                pl.col('track.bpm').is_null()
                | (pl.col('track.bpm').ge(self.song_bpm_range[0])
                   & pl.col('track.bpm').le(self.song_bpm_range[1])))

        # Courtesy of James B. (for the release_date filter suggestion)
        if self.match_song_release_date is not None:
            matching_tracks = matching_tracks.filter(
                self.match_song_release_date)

        return TrackSet(
            matching_tracks,
            is_filtered=self.has_filters or tracks_to_filter.is_filtered,
        )


@dataclass(slots=True)
class TrackLyricsSet:
    track_lyrics: PolarsLazyFrame[TrackLyrics]
    is_filtered: bool

    def filter_tracks(self, tracks_to_filter: TrackSet, *, include_lyrics: bool = False) -> TrackSet:
        """Filter the specified tracks to only include tracks with matching lyrics."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered and not include_lyrics:
            return tracks_to_filter

        return TrackSet(
            tracks_to_filter.tracks.join(
                self.track_lyrics,
                how='inner' if include_lyrics else 'semi',
                on='track.id'),
            is_filtered=self.is_filtered or tracks_to_filter.is_filtered,
        )


@dataclass(slots=True)
class TrackLyricsFilter:
    """Lyrics-specific filters."""

    # User-provided parameters
    lyrics_include: str = ''
    lyrics_exclude: str = ''
    lyrics_limit: int | None = None

    # Parsed filters
    match_lyrics: pl.Expr = field(init=False)
    match_excluded_lyrics: pl.Expr = field(init=False)

    def __post_init__(self):
        """Parses the user-provided filter specifications."""
        self.match_lyrics =\
            create_text_filter(self.lyrics_include,
                               pl.col('track.lyrics'))
        self.match_excluded_lyrics =\
            create_text_filter(self.lyrics_exclude,
                               pl.col('track.lyrics'))

    @property
    def has_filters(self) -> bool:
        """Returns whether any lyrics filters are defined."""
        return self.match_lyrics is not None\
            or self.match_excluded_lyrics is not None

    def filter_lyrics(
        self,
        lyrics_to_filter: TrackLyricsSet,
        *,
        include_full_lyrics: bool = False,
        include_matched_lyrics: bool = False
    ) -> TrackLyricsSet:
        """Filter the specified lyrics_to_filter to only include lyrics matching this filter."""
        matching_track_lyrics = lyrics_to_filter.track_lyrics

        if self.match_lyrics is not None:
            matching_track_lyrics = matching_track_lyrics.filter(
                self.match_lyrics)

        if self.match_excluded_lyrics is not None:
            matching_track_lyrics = matching_track_lyrics.filter(
                ~self.match_excluded_lyrics)

        if include_matched_lyrics and self.match_lyrics is not None:
            matching_track_lyrics = matching_track_lyrics\
                .slice(0, self.lyrics_limit or None)\
                .with_columns(
                    pl.col('track.lyrics')
                    .str.to_lowercase()
                    .str.extract_all('|'.join(self.lyrics_include.lower().split(',')))
                    .list.eval(pl.element().str.to_lowercase())
                    .list.unique()
                    .alias('matched_lyrics'))\
                .with_columns(
                    pl.col('matched_lyrics').list.len().alias('matched_lyrics_count'))

        if not include_full_lyrics:
            matching_track_lyrics = matching_track_lyrics.drop('track.lyrics')

        return TrackLyricsSet(
            matching_track_lyrics,
            is_filtered=self.has_filters or lyrics_to_filter.is_filtered,
        )


@dataclass(kw_only=True)
class CombinedData:
    """Holder for the different underlying data sources."""

    playlists: PolarsLazyFrame[Playlist]
    playlist_tracks: PolarsLazyFrame[PlaylistTrack]
    tracks: PolarsLazyFrame[Track]
    tracks_adjacent: PolarsLazyFrame[TrackAdjacent]
    track_lyrics: PolarsLazyFrame[TrackLyrics] | None = None
    countries: list[str]

    @property
    def all_playlists(self) -> PlaylistSet:
        return PlaylistSet(self.playlists, None, self.playlists, is_filtered=False)

    @property
    def all_playlist_tracks(self) -> PlaylistTrackSet:
        return PlaylistTrackSet(self.playlist_tracks, is_filtered=False)

    @property
    def all_tracks(self) -> TrackSet:
        return TrackSet(self.tracks, is_filtered=False)

    @property
    def all_track_lyrics(self):
        return TrackLyricsSet(self.track_lyrics, is_filtered=False)

    @staticmethod
    def create(
        *,
        playlists: PolarsLazyFrame[Playlist],
        playlist_tracks: PolarsLazyFrame[PlaylistTrack],
        tracks: PolarsLazyFrame[Track],
        countries: pl.DataFrame,
        tracks_adjacent: pl.LazyFrame | None = None,
        track_lyrics: pl.LazyFrame | None = None,
    ):
        """Set the source data for the search engine."""
        return CombinedData(
            playlists=playlists,
            playlist_tracks=playlist_tracks,
            tracks=tracks,
            tracks_adjacent=tracks_adjacent,
            track_lyrics=track_lyrics,
            countries=extract_countries(countries),
        )

    @staticmethod
    def load_from_files():
        """Load the pre-generated data from the Parquet files."""
        return CombinedData(
            playlists=pl.scan_parquet(PLAYLIST_DATA_FILE),
            playlist_tracks=pl.scan_parquet(PLAYLIST_TRACKS_DATA_FILE),
            tracks=pl.scan_parquet(TRACK_DATA_FILE),
            tracks_adjacent=pl.scan_parquet(TRACK_ADJACENT_DATA_FILE),
            track_lyrics=pl.scan_parquet(TRACK_LYRICS_DATA_FILE),
            countries=extract_countries(pl.read_parquet(COUNTRY_DATA_FILE)),
        )


@dataclass(slots=True)
class CombinedFilter:
    playlist_filter: PlaylistFilter = field(default_factory=PlaylistFilter)
    """Filters applied to playlist information."""

    playlist_track_filter: PlaylistTrackFilter = field(default_factory=PlaylistTrackFilter)
    """Filters applied to playlist membership information. """

    track_filter: TrackFilter = field(default_factory=TrackFilter)
    """Filters applied to track information."""

    lyrics_filter: TrackLyricsFilter = field(default_factory=TrackLyricsFilter)
    """Filters applied to track lyrics."""

    aggregate_by: Literal[
        'playlist',
        'owner',
        'track',
        'artist',
    ] | None = 'track'
    """Whether to aggregate the returned dataset by playlists, tracks, (playlist) owners or (track) artists."""

    playlist_in_result: bool = True
    """Whether to include playlist-related columns in the returned dataset."""

    playlist_track_in_result: bool = True
    """Whether to include playlist-membership-related columns in the returned dataset."""

    track_in_result: bool = True
    """Whether to include track-related columns in the returned dataset."""

    lyrics_in_result: bool = True
    """Whether to included lyrics-related columns in the returned dataset."""

    def get_optimal_filter_order(self) -> Literal['playlists_first', 'playlists_and_tracks_first'] | list[FilteredBy]:
        """
        Decide the performance-optimal filtering order for the current query.

        There are two possible directions we can aggregate our result,
        which ultimately lead to the same dataset (minus ordering),
        but may have different performance characteristics:

        1.  Go playlists => playlist\\_tracks => tracks:
        2.  Go (playlists & tracks) => playlist\\_tracks => tracks:

        Abstracting from the technical details & considerations, this boils
        down to estimating which one of `len(filter_playlists(all_playlists))`
        and `len(filter_tracks(all_tracks))` will be smaller, and choosing the
        evaluation order based on that.
        ```
        """

        if not self.playlist_filter.has_filters and not self.playlist_track_filter.has_filters:
            return 'playlists_and_tracks_first'

        return 'playlists_first'

    def apply_filters(
            self,
            data: CombinedData,
            *,
            order: Literal['playlists_first', 'tracks_first'] | list[FilteredBy],
            aggregate_by: Literal[
                'playlist',
                'owner',
                'track',
                'artist',
            ] = 'track'
    ):
        if order == 'playlists_first':
            # Filter playlists, then filter the entries in those playlists,
            # then filter the tracks referenced by those entries
            matching_playlists =\
                self.playlist_filter.filter_playlists(
                    data.all_playlists)

            matching_playlist_tracks =\
                self.playlist_track_filter.filter_playlist_tracks(
                    matching_playlists.filter_playlist_tracks(
                        data.all_playlist_tracks,
                        include_playlist_info=self.playlist_in_result))

            matching_lyrics =\
                self.lyrics_filter.filter_lyrics(
                    data.all_track_lyrics,
                    include_full_lyrics=False,
                    include_matched_lyrics=self.lyrics_in_result)

            matching_tracks =\
                self.track_filter.filter_tracks(
                    matching_lyrics.filter_tracks(
                        matching_playlist_tracks.filter_tracks(
                            data.all_tracks,
                            include_playlist_track_info=self.playlist_track_in_result),
                        include_lyrics=self.lyrics_in_result))
        elif order == 'playlists_and_tracks_first':
            # Filter playlists & tracks separately, filter the entries
            # from those playlists with matching tracks, then join the
            # result back into the tracks
            matching_playlists =\
                self.playlist_filter.filter_playlists(
                    data.all_playlists)

            matching_lyrics =\
                self.lyrics_filter.filter_lyrics(
                    data.all_track_lyrics,
                    include_full_lyrics=False,
                    include_matched_lyrics=self.lyrics_in_result)

            matching_tracks =\
                self.track_filter.filter_tracks(
                    matching_lyrics.filter_tracks(
                        data.all_tracks,
                        include_lyrics=self.lyrics_in_result))

            matching_playlist_tracks =\
                self.playlist_track_filter.filter_playlist_tracks(
                    matching_tracks.filter_playlist_tracks(
                        matching_playlists.filter_playlist_tracks(
                            data.all_playlist_tracks,
                            include_playlist_info=self.playlist_in_result)))

            matching_tracks =\
                matching_playlist_tracks.filter_tracks(
                    matching_tracks,
                    include_playlist_info=self.playlist_in_result,
                    include_playlist_track_info=self.playlist_track_in_result)

        elif isinstance(order, list):
            playlists = data.all_playlists
            playlist_tracks = data.all_playlist_tracks
            tracks = data.all_tracks
            lyrics = data.all_track_lyrics

            for filter in order:
                match filter:
                    case FilteredBy.Playlist:
                        playlists = self.playlist_filter.filter_playlists(playlists)
                        playlist_tracks = playlists.filter_playlist_tracks(
                            playlist_tracks, include_playlist_info=self.playlist_in_result)

                    case FilteredBy.PlaylistTrack:
                        playlist_tracks = self.playlist_track_filter.filter_playlist_tracks(playlist_tracks)
                        playlists = playlist_tracks.filter_playlists(playlists)
                        tracks = playlist_tracks.filter_tracks(
                            tracks, include_playlist_track_info=self.playlist_track_in_result)

                    case FilteredBy.Lyrics:
                        lyrics = self.lyrics_filter.filter_lyrics(
                            lyrics, include_full_lyrics=False, include_matched_lyrics=self.lyrics_in_result)
                        tracks = lyrics.filter_tracks(
                            tracks, include_lyrics=self.lyrics_in_result)

                    case FilteredBy.Track:
                        tracks = self.track_filter.filter_tracks(tracks)
                        lyrics = tracks.filter_lyrics(lyrics)
                        playlist_tracks = tracks.filter_playlist_tracks(
                            playlist_tracks, include_track_info=self.track_in_result)
                    case _:
                        raise ValueError(f'Invalid filter name: {filter}')

                matching_playlists = playlists
                matching_playlist_tracks = playlist_tracks
                matching_tracks = tracks
                matching_lyrics = lyrics

        else:
            raise ValueError(f'Invalid order value: {order}')

        aggregation_mode = aggregate_by or self.aggregate_by

        # NOTE: This protects users from limitations of the current implementation
        if aggregation_mode != 'track' and not isinstance(order, list):
            raise ValueError(f'Aggregation mode {aggregation_mode} is not allowed for non-custom filter orders')

        match aggregation_mode:
            case 'playlist':
                return matching_playlists
            case 'owner':
                return matching_playlists.group_by('owner.id')
            case 'track':
                return matching_tracks
            case 'artist':
                # TODO: Group by individual artists
                return matching_tracks.group_by('track.artists.name')
            case _:
                raise ValueError(f'Invalid aggregate_by value: {aggregate_by}')

    def filter_tracks(self, data: CombinedData) -> TrackSet:
        return self.apply_filters(
            data,
            order=self.get_optimal_filter_order(),
            aggregate_by='track')


class SearchEngine:
    """Encapsulates the logic of filtering for specific songs, playlists etc."""

    data: CombinedData

    def set_data(self, **kwargs):
        """Set the source data for the search engine."""
        self.data = CombinedData.create(**kwargs)

    def load_data(self):
        """Load the pre-generated data from the Parquet files."""
        self.data = CombinedData.load_from_files()

    def get_stats(self) -> tuple[int, int, int, int, int]:
        """Compute statistics about the database content."""
        songs_count, = count_n_unique(self.data.tracks, ['track.id'])
        # TODO: Count the number of unique artsits within track.artists instead
        artists_count, = count_n_unique(
            self.data.tracks, ['track.artists.name'])
        playlists_count, djs_count = count_n_unique(
            self.data.playlists, ['playlist.name', 'owner.name'])
        lyrics_count = count_n_unique(
            self.data.track_lyrics.join(
                self.data.tracks, how='inner', on='track.id'),
            ['track.name', 'track.artists.name'],
            single_key=True)
        return songs_count, artists_count, playlists_count, djs_count, lyrics_count

    def get_dj_stats(
        self,
        *,
        playlist_limit: int | None = 30,
        dj_limit: int | None = 2000,
    ) -> pl.LazyFrame:
        """Get statistics about the different WCS DJs."""
        # Courtesy of Lino V. (for the DJ stats feature suggestion)
        return self.find_djs(playlist_limit=playlist_limit, dj_limit=dj_limit)

    def find_songs(
        self,
        *,
        #
        # Track-specific filters
        #
        song_name: str = '',
        song_bpm_range: tuple[int, int] | None = None,
        song_release_date: str = '',
        artist_name: str = '',
        artist_is_queer: bool = False,
        artist_is_poc: bool = False,
        lyrics_include: str = '',
        lyrics_exclude: str = '',
        lyrics_limit: int | None = None,
        lyrics_in_result: bool = False,
        #
        # Playlist-specific filters
        #
        country: str | list[str] = '',
        dj_name: str = '',
        dj_name_exclude: str = '',
        playlist_include: str = '',
        playlist_exclude: str = '',
        playlist_in_result: bool = True,
        #
        # Playlist-membership specific filters
        #
        added_to_playlist_date: str = '',
        playlist_track_in_result: bool = True,
        #
        # Result options
        #
        sort_by: Literal[
            'playlist_count',
            'dj_count',
            'matched_lyrics_count',
        ] | None = None,
        descending: bool = True,
        skip_num_top_results: int = 0,
        limit: int | None = None,
    ) -> pl.LazyFrame:
        """Returns the songs that match the given query."""

        #####################
        # Filter parameters #
        #####################

        playlist_filter = PlaylistFilter(
            country=country,
            dj_name=dj_name,
            dj_name_exclude=dj_name_exclude,
            playlist_include=playlist_include,
            playlist_exclude=playlist_exclude,
        )

        playlist_track_filter = PlaylistTrackFilter(
            added_to_playlist_date=added_to_playlist_date,
        )

        track_filter = TrackFilter(
            song_name=song_name,
            song_bpm_range=song_bpm_range,
            song_release_date=song_release_date,
            artist_name=artist_name,
            artist_is_queer=artist_is_queer,
            artist_is_poc=artist_is_poc,
        )

        lyrics_filter = TrackLyricsFilter(
            lyrics_include=lyrics_include,
            lyrics_exclude=lyrics_exclude,
            lyrics_limit=lyrics_limit,
        )

        combined_filter = CombinedFilter(
            aggregate_by='track',
            playlist_filter=playlist_filter,
            playlist_in_result=playlist_in_result,
            playlist_track_filter=playlist_track_filter,
            playlist_track_in_result=playlist_track_in_result,
            track_filter=track_filter,
            track_in_result=True,
            lyrics_filter=lyrics_filter,
            lyrics_in_result=lyrics_in_result,
        )

        #####################
        # Perform filtering #
        #####################

        matching_tracks = combined_filter.filter_tracks(self.data)

        return matching_tracks.with_extra_columns()\
            .sort_by(sort_by, descending=descending)\
            .tracks.slice(skip_num_top_results, limit or None)

    def find_playlists(
        self,
        *,
        song_name: str = '',
        artist_name: str = '',
        country: str = '',
        dj_name: str = '',
        playlist_include: str = '',
        playlist_exclude: str = '',
        limit: int | None = None,
    ) -> pl.LazyFrame:
        """Returns the playlists that match the given query."""

        #####################
        # Filter parameters #
        #####################

        track_filter = TrackFilter(
            song_name=song_name,
            artist_name=artist_name,
        )

        playlist_filter = PlaylistFilter(
            country=country,
            dj_name=dj_name,
            playlist_include=playlist_include,
            playlist_exclude=playlist_exclude,
        )

        #####################
        # Perform filtering #
        #####################

        matching_tracks =\
            track_filter.filter_tracks(self.data.all_tracks)

        if matching_tracks.is_filtered:
            matching_playlists =\
                playlist_filter.filter_playlists(
                    matching_tracks.filter_playlists(
                        self.data.all_playlist_tracks,
                        self.data.all_playlists))
        else:
            matching_playlists = \
                playlist_filter.filter_playlists(
                    self.data.all_playlists)

        return matching_playlists.with_extra_columns()\
            .included_playlists.slice(0, limit or None)

    def find_djs(
        self,
        *,
        dj_name: str = '',
        playlist_name: str = '',
        playlist_limit: int | None = 30,
        dj_limit: int | None = 100,
    ) -> pl.LazyFrame:
        """Returns DJs that match the given query."""

        # Courtesy of Lino V. (for the DJ stats feature suggestion)

        #####################
        # Filter parameters #
        #####################

        playlist_filter = PlaylistFilter(
            dj_name=dj_name,
            playlist_include=playlist_name,
        )

        #####################
        # Perform filtering #
        #####################

        matching_playlists =\
            playlist_filter.filter_playlists(
                self.data.all_playlists)

        return matching_playlists\
            .filter_tracks(self.data.all_playlist_tracks, self.data.all_tracks)\
            .tracks.group_by('owner.name', 'owner.id')\
            .agg(pl.n_unique('track.id').alias('song_count'),
                 pl.n_unique('track.artists.name').alias('artist_count'),
                 pl.n_unique('playlist.name').alias('playlist_count'),
                 pl.col('playlist.name').drop_nulls().unique()
                 .sort().slice(0, playlist_limit or None))\
            .with_columns(
                pl.when(pl.col('owner.id').is_not_null()).then(pl.concat_str(
                    pl.lit('https://open.spotify.com/user/'), 'owner.id')).alias('owner.url'))\
            .sort('playlist_count', descending=True)\
            .slice(0, dj_limit or None)

    def find_related_songs(
        self,
        direction: Literal['any', 'prev', 'next'],
        *,
        song_name: str = '',
        artist_name: str = '',
        limit: int | None = 100,
    ) -> tuple[pl.LazyFrame, pl.LazyFrame]:
        """Returns the songs most often played before resp. after the specified song."""

        if self.data.tracks_adjacent is None:
            raise RuntimeError(
                'self.data.tracks_adjacent must be initialized to use related track lookup')

        track_filter = TrackFilter(
            song_name=song_name,
            artist_name=artist_name,
        )

        matching_tracks =\
            track_filter.filter_tracks(
                self.data.all_tracks)

        def find_adjacent_tracks(starting_tracks, direction: Literal['prev', 'next']):
            if direction == 'next':
                this_song_id = 'pair1.track.id'
                other_song_id = 'pair2.track.id'
            elif direction == 'prev':
                this_song_id = 'pair2.track.id'
                other_song_id = 'pair1.track.id'
            else:
                raise ValueError(f'Invalid value for direction: {direction}')

            return self.data.tracks_adjacent.join(
                starting_tracks,
                how='semi',
                left_on=this_song_id,
                    right_on='track.id',
            ).select(
                pl.col(other_song_id).alias('track.id'),
                pl.col('playlist_count').alias('times_played_together')
            )

        if direction == 'any':
            adjacent_track_ids = pl.concat([
                find_adjacent_tracks(matching_tracks.tracks, 'prev'),
                find_adjacent_tracks(matching_tracks.tracks, 'next')
            ]).group_by('track.id').agg(
                pl.col('times_played_together').sum(),
            )
        else:
            adjacent_track_ids = find_adjacent_tracks(
                matching_tracks.tracks, direction)

        adjacent_tracks = TrackSet(adjacent_track_ids.join(
            self.data.tracks, how='inner', on='track.id'), is_filtered=True)

        return (matching_tracks.with_extra_columns().tracks.limit(100),
                adjacent_tracks.with_extra_columns()
                .tracks.sort('times_played_together', descending=True)
                .slice(0, limit or None))
