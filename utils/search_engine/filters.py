from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple

import polars as pl
import polars.selectors as cs

from utils.search_engine.entity import Playlist, PlaylistOwner, PlaylistTrack, Track, TrackLyrics
from utils.search_engine.entity_base import PolarsLazyFrame
from utils.search_utils.filters import create_date_filter, create_text_filter, or_filter


class FilterOrder(StrEnum):
    Playlists_First = 'playlists_first'
    PlaylistsAndTracks_First = 'playlists_and_tracks_first'


class FilterType(StrEnum):
    Playlist = 'playlist'
    PlaylistTrack = 'playlist_track'
    Track = 'track'
    Lyrics = 'lyrics'


class PreFilterOptions(NamedTuple):
    sort_by: str
    """The field to sort by."""

    limit: int
    """Grab the first N results after sorting."""

    descending: bool
    """Whether to sort in descending instead of ascending order."""


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
                    pl.lit('https://open.spotify.com/track/'), Playlist.id)).alias(Playlist.url)),
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

    def filter_playlist_tracks(self, playlist_tracks: PlaylistTrackSet, *, include_playlist_info: bool) -> PlaylistTrackSet:
        """Filter the specified playlist_tracks to only include tracks from matched playlists."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered and not include_playlist_info:
            return playlist_tracks

        matching_playlist_tracks = self.included_playlists.join(
            playlist_tracks.included_playlist_tracks,
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

    def filter_playlists(self, playlists: PlaylistSet) -> PlaylistSet:
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

        return PlaylistSet(
            included_playlists=matching_playlists,
            excluded_playlists=excluded_playlists,
            all_playlists=playlists.all_playlists,
            is_filtered=self.has_filters or playlists.is_filtered,
        )


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

            if include_playlist_info:
                columns_to_select |= Playlist.matching_columns()
                columns_to_select |= Playlist.Owner.matching_columns()

            if include_playlist_track_info:
                columns_to_select |= PlaylistTrack.matching_columns()

            matching_playlist_tracks = self.included_playlist_tracks\
                .group_by(Track.id)\
                .agg(columns_to_select.slice(0, playlist_limit))
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


@dataclass(slots=True)
class TrackSet:
    """A collection of tracks. Each `track.id` should appear at most once with each collection."""
    included_tracks: PolarsLazyFrame[Track]  # TrackWithPlaylist
    is_filtered: bool

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

    def filter_playlists(self, playlist_tracks: PlaylistTrackSet, playlists: PlaylistSet) -> PlaylistSet:
        """Filter the specified playlists to only include playlists that contain at least one track from this set."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered:
            return playlists

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
