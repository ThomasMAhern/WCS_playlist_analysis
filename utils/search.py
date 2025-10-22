"""
Use the user-provided query parameters to filter the underlying database.

The file is structured as follows:

- Common utilities and file name constants.
- Individual filter & join implementations for the playlist/track/... tables.
- Logic for executing the combined filters in the most performance order (`CombinedFilter`).
- Public API for running the different queries (`SearchEngine`).

Individual Filters & Joins
==========================

Playlists
---------

Every playlist row represents a single playlist from Spotify (or another source).

- `PlaylistFilter` filters the rows from `data_playlist_metadata.parquet` by playlist name, DJ name etc.
- `PlaylistSet` joins the filtered playlist rows with the other tables.

Playlist Tracks
---------------

Every `playlist_tracks` row represents an entry in a playlist - that is,
which tracks are added to which playlists (and when).

- `PlaylistTrackFilter` filters the rows from `data_playlist_tracks.parquet` by `added_at` date.
- `PlaylistTrackSet` joins the filtered playlist track rows with the other tables.

Tracks
------

Every track row represents a single unique track from Spotify. Tracks have been unified
so that each "Artist + Track Name" combination is represented by a single track ID.

- `TrackFilter` filters the rows from `data_song_metadata.parquet` by track name, artist name, release date etc.
- `TrackSet` joins the filtered track rows with the other tables.

Track Lyrics
------------

Every `track_lyrics` row represents a track for which we have lyrics information.

- `TrackLyricsFilter` filters the rows from `data_song_lyrics.parquet` by words that are (or aren't) included in the lyrics.
- `TrackLyricsSet` joins the filtered track lyrics with the main track metadata.

Combined Filter
===============

There are different possible orders for the joins (and filters) of the different tables.
The best order depends on the query parameters, and is chosen heuristically based on the
order that is most likely to minimize the number of rows that need to be processed.

The `CombinedFilter` class implements the corresponding heuristics as well as the
sequencing of the filters/joins, while the `CombinedData` class simply serves as
a basic holder for the loaded Parquet files.

Search Engine
=============

The `SearchEngine` class provides public methods (like `find_songs`, `find_playlists` etc.)
for running the different possible queries over the data.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Literal, NamedTuple

import polars as pl
import polars.selectors as cs

from utils.common.entities import PolarsLazyFrame
from utils.common.filters import create_date_filter, create_text_filter, or_filter
from utils.common.stats import count_n_unique
from utils.tables import Playlist, PlaylistOwner, PlaylistTrack, Stats, Track, TrackAdjacent, TrackLyrics


####################
# COMMON UTILITIES #
####################


class PreFilterOptions(NamedTuple):
    sort_by: str
    """The field to sort by."""

    limit: int
    """Grab the first N results after sorting."""

    descending: bool
    """Whether to sort in descending instead of ascending order."""


##########################
# SOURCE DATA FILE NAMES #
##########################

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
COUNTRY_DATA_FILE: Final = DATA_DIR + 'data_countries.csv'
REGION_DATA_FILE: Final = DATA_DIR + 'data_regions.csv'

TRACK_DUPLICATES_DATA_FILE: Final = DATA_DIR + 'data_song_duplicates.parquet'
TRACK_CANONICAL_DATA_FILE: Final = DATA_DIR + 'data_song_canonical.parquet'


#############################
# INDIVIDUAL FILTER & JOINS #
#############################


# ----------------------------
# Playlists: Filtering & Joins
# ----------------------------


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
                pl.when(pl.col(Playlist.id).is_not_null()).then(pl.concat_str(
                    pl.lit('https://open.spotify.com/playlist/'), Playlist.id)).alias(Playlist.url)),
            excluded_playlists=self.excluded_playlists,
            all_playlists=self.all_playlists,
            is_filtered=self.is_filtered)

    def with_owner_url(self):
        return PlaylistSet(
            included_playlists=self.included_playlists.with_columns(
                pl.when(pl.col(PlaylistOwner.id).is_not_null()).then(pl.concat_str(
                    pl.lit('https://open.spotify.com/user/'), PlaylistOwner.id)).alias(PlaylistOwner.url)),
            excluded_playlists=self.excluded_playlists,
            all_playlists=self.all_playlists,
            is_filtered=self.is_filtered)

    def with_extra_columns(self):
        return self\
            .with_playlist_url()\
            .with_owner_url()

    def sort_by(self, by, *more_by, descending: bool):
        return (self if by is None or (isinstance(by, list) and len(by) == 0) else
                PlaylistSet(included_playlists=self.included_playlists.sort(by, *more_by, descending=descending),
                            excluded_playlists=self.excluded_playlists,
                            all_playlists=self.all_playlists,
                            is_filtered=self.is_filtered))

    def filter_playlist_tracks(self, playlist_tracks: PlaylistTrackSet, *, include_playlist_info: bool) -> PlaylistTrackSet:
        """Filter the specified playlist_tracks to only include tracks from matched playlists."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered and not include_playlist_info:
            return playlist_tracks

        matching_playlist_tracks = playlist_tracks.included_playlist_tracks.join(
            self.included_playlists,
            how='inner' if include_playlist_info else 'semi',
            on=Playlist.id)

        if self.excluded_playlists is not None:
            excluded_playlist_tracks = self.excluded_playlists.join(
                playlist_tracks.included_playlist_tracks, how='inner', on=Playlist.id)

            matching_playlist_tracks = matching_playlist_tracks.join(
                excluded_playlist_tracks, how='anti', on=Track.id)

        return PlaylistTrackSet(
            matching_playlist_tracks,
            is_filtered=self.is_filtered or playlist_tracks.is_filtered
        )

    def filter_tracks(self, playlist_tracks: PlaylistTrackSet, tracks: TrackSet, *, include_playlist_info: bool, include_playlist_track_info: bool, playlist_limit: int | None) -> TrackSet:
        """Filter the specified tracks to only include tracks from matched playlists."""
        matching_playlist_tracks =\
            self.filter_playlist_tracks(
                playlist_tracks,
                include_playlist_info=include_playlist_info)

        matching_tracks =\
            matching_playlist_tracks.filter_tracks(
                tracks,
                playlist_limit=playlist_limit,
                include_playlist_info=include_playlist_info,
                include_playlist_track_info=include_playlist_track_info)

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
            create_text_filter(self.dj_name, PlaylistOwner.name),
            create_text_filter(self.dj_name, PlaylistOwner.id))

        self.match_dj_name_exclude = or_filter(
            create_text_filter(self.dj_name_exclude, PlaylistOwner.name),
            create_text_filter(self.dj_name_exclude, PlaylistOwner.id))

        self.match_country =\
            create_text_filter(self.country, Playlist.country)

        self.match_playlist =\
            create_text_filter(self.playlist_include, Playlist.name)

        self.match_excluded_playlist =\
            create_text_filter(self.playlist_exclude, Playlist.name)

    @property
    def has_filters(self) -> bool:
        """Returns whether any playlist filters are defined."""
        return self.match_dj_name is not None\
            or self.match_dj_name_exclude is not None\
            or self.match_country is not None\
            or self.match_playlist is not None\
            or self.match_excluded_playlist is not None

    def filter_playlists(self, playlists: PlaylistSet, *, include_matched_terms: bool) -> PlaylistSet:
        """Filter the specified playlists to only include playlists matching this filter."""
        matching_playlists = playlists.included_playlists

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
            excluded_playlists = playlists.all_playlists.filter(anti_predicate)\
                .select(Playlist.id)

            # But as an optimization, we also want to avoid including those playlists in the first place.
            matching_playlists = matching_playlists.filter(
                anti_predicate.not_())

            # Also keep the list of playlists to exclude from before
            if playlists.excluded_playlists is not None:
                excluded_playlists = pl.concat([
                    excluded_playlists,
                    playlists.excluded_playlists,
                ]).unique(Playlist.id)
        else:
            excluded_playlists = playlists.excluded_playlists

        if include_matched_terms and self.match_playlist is not None:
            matching_playlists = matching_playlists\
                .with_columns(
                    pl.col(Playlist.name)
                    .str.to_lowercase()
                    .str.extract_all('|'.join(self.playlist_include.lower().split(',')))
                    .list.eval(pl.element().str.to_lowercase())
                    .list.unique()
                    .list.sort()
                    .alias(Playlist.matched_terms))\
                .with_columns(
                    pl.col(Playlist.matched_terms).list.len()
                    .alias(Playlist.matched_terms_count))
        elif include_matched_terms:
            matching_playlists = matching_playlists\
                .with_columns(
                    pl.lit([]).cast(pl.List(pl.String)).alias(Playlist.matched_terms),
                    pl.lit(0).alias(Playlist.matched_terms_count))

        return PlaylistSet(
            included_playlists=matching_playlists,
            excluded_playlists=excluded_playlists,
            all_playlists=playlists.all_playlists,
            is_filtered=self.has_filters or playlists.is_filtered,
        )


# ----------------------------------
# Playlist Tracks: Filtering & Joins
# ----------------------------------


@dataclass(slots=True)
class PlaylistTrackSet:
    """A collection of playlist-to-track relations."""
    included_playlist_tracks: PolarsLazyFrame[PlaylistTrack]  # PlaylistTrackWithPlaylist
    is_filtered: bool

    def filter_playlists(self, playlists: PlaylistSet) -> PlaylistSet:
        """Filter the specified playlists to only include playlists mentioned in this set."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered:
            return playlists

        matching_playlists = playlists.included_playlists.join(
            self.included_playlist_tracks,
            how='semi',
            on=Playlist.id)

        return PlaylistSet(
            included_playlists=matching_playlists,
            excluded_playlists=playlists.excluded_playlists,
            all_playlists=playlists.all_playlists,
            is_filtered=self.is_filtered or playlists.is_filtered,
        )

    def filter_tracks(self, tracks: TrackSet, *, include_playlist_info: bool, include_playlist_track_info: bool, playlist_limit: int | None) -> TrackSet:
        """Filter the specified tracks to only include tracks from playlists in this set."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered and not include_playlist_info and not include_playlist_track_info:
            return tracks

        if include_playlist_info or include_playlist_track_info:
            columns_to_select = cs.empty()
            additional_aggregate_columns: list[pl.Expr] = []
            additional_columns: list[pl.Expr] = []

            if include_playlist_info:
                columns_to_select |= Playlist.matching_columns()

                additional_aggregate_columns.append(
                    PlaylistOwner.matching_columns().as_expr()
                    .unique().sort().slice(0, playlist_limit))

                additional_aggregate_columns.append(
                    pl.col(Playlist.id).n_unique().alias(Playlist.matching_playlist_count))

                additional_aggregate_columns.append(
                    cs.matches("^" + Playlist.matched_terms + "$")
                    .as_expr().flatten().implode().list.unique().list.sort())

                additional_columns.append(
                    cs.matches("^" + Playlist.matched_terms + "$")
                    .as_expr().list.len().alias(Playlist.matched_terms_count))

            if include_playlist_track_info:
                columns_to_select |= PlaylistTrack.matching_columns()

            matching_playlist_tracks = self.included_playlist_tracks\
                .group_by(Track.id)\
                .agg(columns_to_select.slice(0, playlist_limit),
                     *additional_aggregate_columns)\
                .with_columns(*additional_columns)
        else:
            matching_playlist_tracks = self.included_playlist_tracks

        matching_tracks = tracks.included_tracks.join(
            matching_playlist_tracks,
            how='inner' if include_playlist_info or include_playlist_track_info else 'semi',
            on=Track.id)

        return TrackSet(
            matching_tracks,
            is_filtered=self.is_filtered or tracks.is_filtered,
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
                               pl.col(PlaylistTrack.added_at))

    @property
    def has_filters(self) -> bool:
        """Returns whether any playlist_track filters are defined."""
        return self.match_added_to_playlist_date is not None

    def filter_playlist_tracks(self, playlist_tracks: PlaylistTrackSet) -> PlaylistTrackSet:
        """Filter the specified playlist_tracks to only include playlist_tracks matching this filter."""
        matching_playlist_tracks = playlist_tracks.included_playlist_tracks

        # Courtesy of Franzi M. (for the added_to_playlist_date filter suggestion)
        if self.match_added_to_playlist_date is not None:
            matching_playlist_tracks = matching_playlist_tracks.filter(
                self.match_added_to_playlist_date)

        return PlaylistTrackSet(
            matching_playlist_tracks,
            is_filtered=self.has_filters or playlist_tracks.is_filtered
        )


# -------------------------
# Tracks: Filtering & Joins
# -------------------------


@dataclass(slots=True)
class TrackSet:
    """A collection of tracks. Each `track.id` should appear at most once with each collection."""
    included_tracks: PolarsLazyFrame[Track]  # TrackWithPlaylist
    is_filtered: bool

    def rename(self, mapping: dict[str, str]):
        return TrackSet(self.included_tracks.rename(mapping),
                        is_filtered=self.is_filtered)

    def with_extra_columns(self):
        return TrackSet(self.included_tracks.with_columns(
            pl.col(Track.beats_per_minute).fill_null(0.0),
            pl.when(pl.col(Track.id).is_not_null()).then(pl.concat_str(
                pl.lit('https://open.spotify.com/track/'), Track.id)).alias(Track.url)),
            is_filtered=self.is_filtered)

    def sort_by(self, by, *more_by, descending: bool):
        return (self if by is None or (isinstance(by, list) and len(by) == 0) else
                TrackSet(self.included_tracks.sort(by, *more_by, descending=descending),
                         is_filtered=self.is_filtered))

    def filter_lyrics(self, lyrics: TrackLyricsSet) -> TrackLyricsSet:
        """Filter the specified track lyrics to only include ones for tracks in this set."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered:
            return lyrics

        return TrackLyricsSet(
            lyrics.included_track_lyrics.join(
                self.included_tracks,
                how='semi',
                on=Track.id),
            is_filtered=True)

    def filter_playlist_tracks(self, playlist_tracks: PlaylistTrackSet, *, include_track_info: bool) -> PlaylistTrackSet:
        """Filter the specified playlist-to-track relations to only include ones for tracks in this set."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered and not include_track_info:
            return playlist_tracks

        matching_playlist_tracks = playlist_tracks.included_playlist_tracks.join(
            self.included_tracks,
            how='inner' if include_track_info else 'semi',
            on=Track.id)

        return PlaylistTrackSet(matching_playlist_tracks,
                                is_filtered=True)

    def filter_playlists(self, playlist_tracks: PlaylistTrackSet, playlists: PlaylistSet, *, tracks_in_result: bool, tracks_limit: int | None) -> PlaylistSet:
        """Filter the specified playlists to only include playlists that contain at least one track from this set."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered and not tracks_in_result:
            return playlists

        if tracks_in_result:
            if self.is_filtered:
                aggregated_tracks_per_playlist = playlist_tracks.included_playlist_tracks\
                    .select(PlaylistTrack.Track.id, PlaylistTrack.Playlist.id)\
                    .join(self.included_tracks.select(Track.id, Track.name), how='inner', on=Track.id)\
                    .join(playlists.included_playlists, how='semi', on=Playlist.id)\
                    .group_by(Playlist.id)\
                    .agg(pl.col(Track.name).unique().slice(0, tracks_limit),
                         pl.col(Track.id).n_unique().alias(Playlist.matching_song_count))
            else:
                aggregated_tracks_per_playlist = playlist_tracks.included_playlist_tracks\
                    .select(PlaylistTrack.Track.id, PlaylistTrack.Playlist.id)\
                    .join(playlists.included_playlists, how='semi', on=Playlist.id)\
                    .join(self.included_tracks.select(Track.id, Track.name), how='inner', on=Track.id)\
                    .group_by(Playlist.id)\
                    .agg(pl.col(Track.name).unique().slice(0, tracks_limit),
                         pl.col(Track.id).n_unique().alias(Playlist.matching_song_count))

            matching_playlists = playlists.included_playlists\
                .join(aggregated_tracks_per_playlist, how='inner', on=Playlist.id)
        else:
            matching_playlists = playlists.included_playlists.join(
                playlist_tracks.included_playlist_tracks.join(
                    self.included_tracks, how='semi', on=Track.id),
                how='semi', on=Playlist.id)

        return PlaylistSet(
            matching_playlists,
            playlists.excluded_playlists,
            playlists.all_playlists,
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

    # Internal optimizations
    pre_filter: PreFilterOptions | None = None

    # Parsed filters
    match_song_name: pl.Expr = field(init=False)
    match_song_release_date: pl.Expr = field(init=False)
    match_artist_name: pl.Expr = field(init=False)

    def __post_init__(self):
        """Parses the user-provided filter specifications."""
        self.match_song_name =\
            create_text_filter(self.song_name, Track.name)
        self.match_song_release_date =\
            create_date_filter(self.song_release_date, Track.release_date)
        self.match_artist_name =\
            create_text_filter(self.artist_name, Track.artist_names)

    @property
    def has_filters(self) -> bool:
        """Returns whether any track filters are defined."""
        return self.match_song_name is not None\
            or self.song_bpm_range is not None\
            or self.match_song_release_date is not None\
            or self.match_artist_name is not None\
            or self.artist_is_queer\
            or self.artist_is_poc\
            or self.pre_filter is not None

    def filter_tracks(self, tracks: TrackSet) -> TrackSet:
        """Filter the specified tracks to only include tracks matching this filter."""
        matching_tracks = tracks.included_tracks

        if self.match_song_name is not None:
            matching_tracks = matching_tracks.filter(
                self.match_song_name)

        if self.match_artist_name is not None:
            matching_tracks = matching_tracks.filter(
                self.match_artist_name)

        if self.artist_is_queer:
            matching_tracks = matching_tracks.filter(
                pl.col(Track.has_queer_artist))

        if self.artist_is_poc:
            matching_tracks = matching_tracks.filter(
                pl.col(Track.has_poc_artist))

        if self.song_bpm_range:
            matching_tracks = matching_tracks.filter(
                pl.col(Track.beats_per_minute).is_null()
                | (pl.col(Track.beats_per_minute).ge(self.song_bpm_range[0])
                   & pl.col(Track.beats_per_minute).le(self.song_bpm_range[1])))

        # Courtesy of James B. (for the release_date filter suggestion)
        if self.match_song_release_date is not None:
            matching_tracks = matching_tracks.filter(
                self.match_song_release_date)

        # Pre-filter the results for certain queries over all tracks
        if self.pre_filter is not None:
            matching_tracks = matching_tracks\
                .sort(self.pre_filter.sort_by, descending=self.pre_filter.descending)\
                .limit(self.pre_filter.limit)

        return TrackSet(matching_tracks, is_filtered=self.has_filters or tracks.is_filtered)


# -------------------------------
# Track Lyrics: Filtering & Joins
# -------------------------------


@dataclass(slots=True)
class TrackLyricsSet:
    included_track_lyrics: PolarsLazyFrame[TrackLyrics]
    is_filtered: bool

    def filter_tracks(self, tracks: TrackSet, *, include_lyrics: bool) -> TrackSet:
        """Filter the specified tracks to only include tracks with matching lyrics."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered and not include_lyrics:
            return tracks

        return TrackSet(
            tracks.included_tracks.join(
                self.included_track_lyrics,
                how='inner' if include_lyrics else 'semi',
                on=Track.id),
            is_filtered=self.is_filtered or tracks.is_filtered,
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
            create_text_filter(self.lyrics_include, TrackLyrics.lyrics)
        self.match_excluded_lyrics =\
            create_text_filter(self.lyrics_exclude, TrackLyrics.lyrics)

    @property
    def has_filters(self) -> bool:
        """Returns whether any lyrics filters are defined."""
        return self.match_lyrics is not None\
            or self.match_excluded_lyrics is not None

    def filter_lyrics(self, lyrics: TrackLyricsSet, *, include_full_lyrics: bool, include_matched_lyrics: bool) -> TrackLyricsSet:
        """Filter the specified lyrics to only include lyrics matching this filter."""
        matching_track_lyrics = lyrics.included_track_lyrics

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
                    pl.col(TrackLyrics.lyrics)
                    .str.to_lowercase()
                    .str.extract_all('|'.join(self.lyrics_include.lower().split(',')))
                    .list.eval(pl.element().str.to_lowercase())
                    .list.unique()
                    .alias(TrackLyrics.matched_lyrics))\
                .with_columns(
                    pl.col(TrackLyrics.matched_lyrics).list.len().alias(TrackLyrics.matched_lyrics_count))

        if not include_full_lyrics:
            matching_track_lyrics = matching_track_lyrics.drop(TrackLyrics.lyrics)

        return TrackLyricsSet(
            matching_track_lyrics,
            is_filtered=self.has_filters or lyrics.is_filtered,
        )


##############################
# COMBINED FILTERING & JOINS #
##############################

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
            countries=pl.read_csv(COUNTRY_DATA_FILE)['country'].to_list(),
        )


class FilterOrder(StrEnum):
    Playlists_First = 'playlists_first'
    PlaylistsAndTracks_First = 'playlists_and_tracks_first'


class FilterType(StrEnum):
    Playlist = 'playlist'
    PlaylistTrack = 'playlist_track'
    Track = 'track'
    Lyrics = 'lyrics'


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

    playlist_limit: int | None = 30
    """Only include up to N playlists in the aggregated columns of the result."""

    playlist_track_in_result: bool = True
    """Whether to include playlist-membership-related columns in the returned dataset."""

    track_in_result: bool = True
    """Whether to include track-related columns in the returned dataset."""

    lyrics_in_result: bool = True
    """Whether to included lyrics-related columns in the returned dataset."""

    def get_optimal_filter_order(self) -> FilterOrder | list[FilterType]:
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
            return FilterOrder.PlaylistsAndTracks_First

        return FilterOrder.Playlists_First

    def apply_filters(
            self,
            data: CombinedData,
            *,
            order: FilterOrder | list[FilterType],
            aggregate_by: Literal[
                'playlist',
                'owner',
                'track',
                'artist',
            ] = 'track'
    ):
        if order == FilterOrder.Playlists_First:
            # Filter playlists, then filter the entries in those playlists,
            # then filter the tracks referenced by those entries
            matching_playlists =\
                self.playlist_filter.filter_playlists(
                    data.all_playlists,
                    include_matched_terms=self.playlist_in_result)

            matching_playlist_tracks =\
                self.playlist_track_filter.filter_playlist_tracks(
                    matching_playlists.filter_playlist_tracks(
                        data.all_playlist_tracks(Playlist.id),
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
                            playlist_limit=self.playlist_limit,
                            include_playlist_info=self.playlist_in_result,
                            include_playlist_track_info=self.playlist_track_in_result),
                        include_lyrics=self.lyrics_in_result))
        elif order == FilterOrder.PlaylistsAndTracks_First:
            # Filter playlists & tracks separately, filter the entries
            # from those playlists with matching tracks, then join the
            # result back into the tracks
            matching_playlists =\
                self.playlist_filter.filter_playlists(
                    data.all_playlists,
                    include_matched_terms=self.playlist_in_result)

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
                            data.all_playlist_tracks(Playlist.id if matching_playlists.is_filtered
                                                     or self.playlist_in_result else Track.id),
                            include_playlist_info=self.playlist_in_result),
                        include_track_info=False))

            matching_tracks =\
                matching_playlist_tracks.filter_tracks(
                    matching_tracks,
                    playlist_limit=self.playlist_limit,
                    include_playlist_info=self.playlist_in_result,
                    include_playlist_track_info=self.playlist_track_in_result)

        elif isinstance(order, list):
            playlists = data.all_playlists
            # TODO: Automatically choose Track.id if that likely leads to better performance
            playlist_tracks = data.all_playlist_tracks(Playlist.id)
            tracks = data.all_tracks
            lyrics = data.all_track_lyrics

            for filter in order:
                match filter:
                    case FilterType.Playlist:
                        playlists = self.playlist_filter.filter_playlists(
                            playlists, include_matched_terms=self.playlist_in_result)
                        playlist_tracks = playlists.filter_playlist_tracks(
                            playlist_tracks, include_playlist_info=self.playlist_in_result)

                    case FilterType.PlaylistTrack:
                        playlist_tracks = self.playlist_track_filter.filter_playlist_tracks(playlist_tracks)
                        playlists = playlist_tracks.filter_playlists(playlists)
                        tracks = playlist_tracks.filter_tracks(
                            tracks,
                            playlist_limit=self.playlist_limit,
                            include_playlist_info=self.playlist_in_result,
                            include_playlist_track_info=self.playlist_track_in_result)

                    case FilterType.Lyrics:
                        lyrics = self.lyrics_filter.filter_lyrics(
                            lyrics, include_full_lyrics=False, include_matched_lyrics=self.lyrics_in_result)
                        tracks = lyrics.filter_tracks(
                            tracks, include_lyrics=self.lyrics_in_result)

                    case FilterType.Track:
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
                return matching_playlists.group_by(PlaylistOwner.id)
            case 'track':
                return matching_tracks
            case 'artist':
                # TODO: Group by individual artists
                return matching_tracks.group_by(Track.artist_names)
            case _:
                raise ValueError(f'Invalid aggregate_by value: {aggregate_by}')

    def filter_tracks(self, data: CombinedData) -> TrackSet:
        return self.apply_filters(
            data,
            order=self.get_optimal_filter_order(),
            aggregate_by='track')


#####################
# PUBLIC SEARCH API #
#####################


type TrackSortKey = Literal[
    'hit_count',
    'playlist_count',
    'dj_count',
    'matching_playlist_count',
    'matched_lyrics_count',
]

type PlaylistSortKey = Literal[
    'hit_count',
    'matching_song_count',
    'song_count',
    'artist_count',
]


class SearchEngine:
    """Encapsulates the logic of filtering for specific songs, playlists etc."""

    data: CombinedData

    def load_data(self):
        """Load the pre-generated data from the Parquet files."""
        self.data = CombinedData.load_from_files()

    def get_stats(self) -> tuple[int, int, int, int, int]:
        """Compute statistics about the database content."""
        songs_count, = count_n_unique(self.data.tracks, [Track.id])
        # TODO: Count the number of unique artsits within track.artists instead
        artists_count, = count_n_unique(
            self.data.tracks, [Track.artist_names])
        playlists_count, djs_count = count_n_unique(
            self.data.playlists, [Playlist.id, PlaylistOwner.name])
        lyrics_count = count_n_unique(
            self.data.track_lyrics.join(
                self.data.tracks, how='inner', on=Track.id),
            [Track.name, Track.artist_names],
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

    def get_region_stats(self) -> pl.LazyFrame:
        """Get some useful database statistics by geographic region."""
        return self.get_grouped_stats(Playlist.region, 'region')

    def get_country_stats(self) -> pl.LazyFrame:
        """Get some useful database statistics by country."""
        return self.get_grouped_stats(Playlist.country, 'country')

    def get_grouped_stats(self, group_by: str, group_header: str) -> pl.LazyFrame:
        song_counts_by_group =\
            self.data.all_playlists.filter_playlist_tracks(
                self.data.all_playlist_tracks(Playlist.id),
                include_playlist_info=True)\
            .included_playlist_tracks.group_by(group_by)\
            .agg(song_count=pl.n_unique(Track.id))

        playlist_counts_by_group =\
            self.data.playlists.group_by(group_by)\
            .agg(playlist_count=pl.n_unique(Playlist.id),
                 dj_count=pl.n_unique(PlaylistOwner.id),
                 djs=pl.col(PlaylistOwner.name))\
            .with_columns(pl.col('djs').list.unique().list.head(30))

        return playlist_counts_by_group\
            .join(song_counts_by_group, how='full', on=group_by, nulls_equal=True)\
            .with_columns(pl.col(group_by).fill_null(pl.col(group_by + "_right")))\
            .select(pl.col(group_by).alias(group_header), 'song_count', 'playlist_count', 'dj_count', 'djs')\
            .sort(group_header)

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
        playlist_limit: int | None = 30,
        #
        # Playlist-membership specific filters
        #
        added_to_playlist_date: str = '',
        playlist_track_in_result: bool = True,
        #
        # Result options
        #
        sort_by: TrackSortKey | list[TrackSortKey] | None = None,
        descending: bool = True,
        skip_num_top_results: int = 0,
        limit: int | None = None,
    ) -> pl.LazyFrame:
        """Returns the songs that match the given query."""

        if isinstance(sort_by, str):
            _sort_by: list[TrackSortKey] = [sort_by]
        elif sort_by is None:
            _sort_by: list[TrackSortKey] = []
        else:
            _sort_by: list[TrackSortKey] = sort_by

        def is_sorted_by_any_of(*columns: TrackSortKey) -> bool:
            if len(columns) == 0:
                raise ValueError("No columns specified")
            if len(_sort_by) == 0:
                return False
            return set(_sort_by).issubset(set(columns))

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
            pre_filter=PreFilterOptions(sort_by, limit, descending)
            if is_sorted_by_any_of('playlist_count', 'dj_count')
            and limit is not None else None,
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
            playlist_limit=playlist_limit,
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
            .included_tracks.slice(skip_num_top_results, limit or None)

    def find_playlists(
        self,
        *,
        #
        # Track-specific filters
        #
        song_name: str = '',
        artist_name: str = '',
        #
        # Playlist-specific filters
        #
        country: str = '',
        dj_name: str = '',
        playlist_include: str = '',
        playlist_exclude: str = '',
        #
        # Result options
        #
        tracks_in_result: bool = False,
        tracks_limit: int | None = None,
        sort_by: PlaylistSortKey | list[PlaylistSortKey] | None = None,
        descending: bool = True,
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

        if matching_tracks.is_filtered or tracks_in_result:
            matching_playlists =\
                playlist_filter.filter_playlists(
                    matching_tracks.filter_playlists(
                        self.data.all_playlist_tracks(Playlist.id),
                        self.data.all_playlists,
                        tracks_in_result=tracks_in_result,
                        tracks_limit=tracks_limit),
                    include_matched_terms=True)
        else:
            matching_playlists =\
                playlist_filter.filter_playlists(
                    self.data.all_playlists,
                    include_matched_terms=True)

        return matching_playlists.with_extra_columns()\
            .sort_by(sort_by, descending=descending)\
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
                self.data.all_playlists,
                include_matched_terms=False)

        return self.data.all_tracks\
            .filter_playlist_tracks(
                matching_playlists.filter_playlist_tracks(
                    self.data.all_playlist_tracks(Playlist.id),
                    include_playlist_info=True),
                include_track_info=True)\
            .included_playlist_tracks.group_by(PlaylistOwner.name, PlaylistOwner.id)\
            .agg(pl.n_unique(Track.id).alias(Stats.song_count),
                 pl.n_unique(Track.artist_names).alias(Stats.artist_count),
                 pl.n_unique(Playlist.name).alias(Stats.playlist_count),
                 pl.col(Playlist.name).drop_nulls().unique()
                 .sort().slice(0, playlist_limit or None))\
            .with_columns(
                pl.when(pl.col(PlaylistOwner.id).is_not_null()).then(pl.concat_str(
                    pl.lit('https://open.spotify.com/user/'), PlaylistOwner.id)).alias(PlaylistOwner.url))\
            .sort(Stats.playlist_count, descending=True)\
            .slice(0, dj_limit or None)

    def find_related_songs(
        self,
        direction: Literal['any', 'prev', 'next'],
        *,
        return_pairs: bool = False,
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

        tracks_adjacent = self.data.tracks_adjacent\
            .rename({Stats.playlist_count: TrackAdjacent.times_played_together})

        if not matching_tracks.is_filtered:
            # Prefilter to avoid very large join
            tracks_adjacent = tracks_adjacent\
                .sort(TrackAdjacent.times_played_together, descending=True)\
                .slice(0, limit)

        def find_adjacent_tracks(starting_tracks: TrackSet, direction: Literal['prev', 'next']):
            if direction == 'next':
                this_song_id = TrackAdjacent.FirstTrack.id
                other_song_id = TrackAdjacent.SecondTrack.id
            elif direction == 'prev':
                this_song_id = TrackAdjacent.SecondTrack.id
                other_song_id = TrackAdjacent.FirstTrack.id
            else:
                raise ValueError(f'Invalid value for direction: {direction}')

            return (tracks_adjacent if not starting_tracks.is_filtered else
                    tracks_adjacent.join(starting_tracks.included_tracks, how='semi',
                                         left_on=this_song_id, right_on=Track.id))\
                .select(pl.col(other_song_id).alias(Track.id),
                        pl.col(this_song_id).alias(TrackAdjacent.FirstTrack.id),
                        pl.col(other_song_id).alias(TrackAdjacent.SecondTrack.id),
                        pl.col(TrackAdjacent.times_played_together))

        if return_pairs:
            if direction == 'any':
                adjacent_track_ids = (
                    pl.concat([
                        find_adjacent_tracks(matching_tracks, 'prev'),
                        find_adjacent_tracks(matching_tracks, 'next')
                    ])
                    # We only want to keep one of [T1,T2,N] and [T2,T1,N]
                    .filter(pl.col(TrackAdjacent.FirstTrack.id).lt(pl.col(TrackAdjacent.SecondTrack.id)))
                    .group_by(TrackAdjacent.FirstTrack.id, TrackAdjacent.SecondTrack.id)
                    .agg(pl.col(TrackAdjacent.times_played_together).sum()))
            else:
                adjacent_track_ids = find_adjacent_tracks(matching_tracks, direction)

            adjacent_tracks = TrackSet(
                adjacent_track_ids
                .select(TrackAdjacent.FirstTrack.id, TrackAdjacent.SecondTrack.id, TrackAdjacent.times_played_together)
                .join(self.data.tracks.select(pl.col(Track.id).alias(TrackAdjacent.FirstTrack.id),
                                              pl.col(Track.name).alias(TrackAdjacent.FirstTrack.name),
                                              pl.col(Track.artists).alias(TrackAdjacent.FirstTrack.artists)),
                      how='inner', on=TrackAdjacent.FirstTrack.id)
                .join(self.data.tracks.select(pl.col(Track.id).alias(TrackAdjacent.SecondTrack.id),
                                              pl.col(Track.name).alias(TrackAdjacent.SecondTrack.name),
                                              pl.col(Track.artists).alias(TrackAdjacent.SecondTrack.artists)),
                      how='inner', on=TrackAdjacent.SecondTrack.id),
                is_filtered=True)

            return (None,
                    adjacent_tracks.included_tracks.sort(TrackAdjacent.times_played_together, descending=True)
                    .slice(0, limit or None))
        else:
            if direction == 'any':
                adjacent_track_ids = pl.concat([
                    find_adjacent_tracks(matching_tracks, 'prev'),
                    find_adjacent_tracks(matching_tracks, 'next')
                ]).group_by(Track.id).agg(
                    pl.col(TrackAdjacent.times_played_together).sum(),
                )
            else:
                adjacent_track_ids = find_adjacent_tracks(matching_tracks, direction)

            adjacent_tracks = TrackSet(adjacent_track_ids.select(Track.id, TrackAdjacent.times_played_together).join(
                self.data.tracks, how='inner', on=Track.id), is_filtered=True)

            return (matching_tracks.with_extra_columns().included_tracks.limit(100),
                    adjacent_tracks.with_extra_columns()
                    .included_tracks.sort(TrackAdjacent.times_played_together, descending=True)
                    .slice(0, limit or None))
