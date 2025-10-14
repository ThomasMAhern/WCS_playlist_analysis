from dataclasses import dataclass, field
from typing import Literal

import polars as pl

from utils.search_engine.entity import Playlist, PlaylistOwner, Stats, Track, TrackAdjacent
from utils.search_engine.filters import FilterOrder, FilterType, PlaylistFilter, PlaylistTrackFilter, PreFilterOptions, TrackFilter, TrackLyricsFilter, TrackSet
from utils.search_engine.source_data import CombinedData
from utils.search_engine.source_data import *  # Export all constants
from utils.search_utils.stats import count_n_unique


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


type SortKey = Literal[
    'hit_count',
    'playlist_count',
    'dj_count',
    'matching_playlist_count',
    'matched_lyrics_count',
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
            self.data.playlists, [Playlist.name, PlaylistOwner.name])
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
        sort_by: SortKey | list[SortKey] | None = None,
        descending: bool = True,
        skip_num_top_results: int = 0,
        limit: int | None = None,
    ) -> pl.LazyFrame:
        """Returns the songs that match the given query."""

        if isinstance(sort_by, str):
            _sort_by: list[SortKey] = [sort_by]
        elif sort_by is None:
            _sort_by: list[SortKey] = []
        else:
            _sort_by: list[SortKey] = sort_by

        def is_sorted_by_any_of(*columns: SortKey) -> bool:
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
                        self.data.all_playlist_tracks(Playlist.id),
                        self.data.all_playlists),
                    include_matched_terms=True)
        else:
            matching_playlists = \
                playlist_filter.filter_playlists(
                    self.data.all_playlists,
                    include_matched_terms=True)

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
                self.data.all_playlists,
                include_matched_terms=False)

        return matching_playlists\
            .filter_tracks(self.data.all_playlist_tracks(Playlist.id), self.data.all_tracks)\
            .included_tracks.group_by(PlaylistOwner.name, PlaylistOwner.id)\
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
                this_song_id = TrackAdjacent.FirstTrack.id
                other_song_id = TrackAdjacent.SecondTrack.id
            elif direction == 'prev':
                this_song_id = TrackAdjacent.SecondTrack.id
                other_song_id = TrackAdjacent.FirstTrack.id
            else:
                raise ValueError(f'Invalid value for direction: {direction}')

            return self.data.tracks_adjacent.join(
                starting_tracks,
                how='semi',
                left_on=this_song_id,
                right_on=Track.id,
            ).select(
                pl.col(other_song_id).alias(Track.id),
                pl.col(Stats.playlist_count).alias(TrackAdjacent.times_played_together)
            )

        if direction == 'any':
            adjacent_track_ids = pl.concat([
                find_adjacent_tracks(matching_tracks.included_tracks, 'prev'),
                find_adjacent_tracks(matching_tracks.included_tracks, 'next')
            ]).group_by(Track.id).agg(
                pl.col(TrackAdjacent.times_played_together).sum(),
            )
        else:
            adjacent_track_ids = find_adjacent_tracks(
                matching_tracks.included_tracks, direction)

        adjacent_tracks = TrackSet(adjacent_track_ids.join(
            self.data.tracks, how='inner', on=Track.id), is_filtered=True)

        return (matching_tracks.with_extra_columns().included_tracks.limit(100),
                adjacent_tracks.with_extra_columns()
                .included_tracks.sort(TrackAdjacent.times_played_together, descending=True)
                .slice(0, limit or None))
