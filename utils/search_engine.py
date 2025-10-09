from dataclasses import dataclass, field
from typing import Callable, Final, Literal, overload

import polars as pl

import utils.types.lazyframes as lf

PLAYLIST_DATA_FILE = 'data_playlist_metadata.parquet'
PLAYLIST_TRACKS_DATA_FILE = 'data_playlist_songs.parquet'
TRACK_DATA_FILE = 'data_song_metadata.parquet'
TRACK_ADJACENT_DATA_FILE = 'data_song_adjacent.parquet'
TRACK_LYRICS_DATA_FILE = 'data_song_lyrics.parquet'
COUNTRY_DATA_FILE = 'data_countries.parquet'


def extract_countries(countries_dataframe: pl.DataFrame) -> list[str]:
    return countries_dataframe['country'].to_list()


def create_text_filter(filter_expression: str | list[str] | None, ascii_case_insensitive: bool = True) -> Callable[[pl.Expr], pl.Expr] | None:
    """Parse a filter expression for a text column."""
    if filter_expression is None:
        return None

    if isinstance(filter_expression, list):
        if ascii_case_insensitive:
            values = [item.lower() for item in filter_expression if item]
        else:
            values = list(filter(bool, filter_expression))
    else:
        if ascii_case_insensitive:
            values = list(
                filter(bool, filter_expression.strip().lower().split(',')))
        else:
            values = list(filter(bool, filter_expression.strip().split(',')))

    if not values:
        return None

    return lambda expr: expr.cast(pl.String).str.contains_any(values, ascii_case_insensitive=ascii_case_insensitive)


def create_date_filter(filter_expression: str) -> Callable[[pl.Expr], pl.Expr] | None:
    """Parse a filter expression for a date column"""
    text_filter = create_text_filter(
        filter_expression, ascii_case_insensitive=False)

    if not text_filter:
        return None

    return lambda expr: text_filter(expr.dt.to_string())


@overload
def count_n_unique(data: pl.LazyFrame, columns: list[str], single_key: Literal[True]) -> int:
    pass


@overload
def count_n_unique(data: pl.LazyFrame, columns: list[str], single_key: Literal[False] = False) -> list[int]:
    pass


def count_n_unique(data: pl.LazyFrame, columns: list[str], single_key: bool = False) -> int | list[int]:
    """Count the number of unique values in the specified columns."""
    if single_key:
        # Count the number of unique combinations of the specified columns
        return list(data.select(pl.concat_list(columns).n_unique().alias('count'))
                    .collect(engine='streaming')
                    .iter_rows())[0][0]

    else:
        # Count each column separately
        return list(list(data.select(pl.n_unique(*columns))
                         .collect(engine='streaming')
                         .iter_rows())[0])


@dataclass
class PlaylistSet:
    included_playlists: lf.Playlists
    excluded_playlists: lf.Playlists | None
    is_filtered: bool

    def with_playlist_url(self):
        return PlaylistSet(
            self.included_playlists.with_columns(
                pl.when(pl.col('playlist.id').is_not_null()).then(pl.concat_str(
                    pl.lit('https://open.spotify.com/track/'), 'playlist.id')).alias('playlist.url')),
            self.excluded_playlists)

    def with_owner_url(self):
        return PlaylistSet(
            self.included_playlists.with_columns(
                pl.when(pl.col('owner.id').is_not_null()).then(pl.concat_str(
                    pl.lit('https://open.spotify.com/user/'), 'owner.id')).alias('owner.url')),
            self.excluded_playlists)

    def with_extra_columns(self):
        return self\
            .with_playlist_url()\
            .with_owner_url()

    def filter_playlist_tracks(self, playlist_tracks_to_filter: lf.PlaylistTracks, include_playlist_info: bool = True) -> lf.PlaylistTracks:
        """Filter the specified playlist_tracks_to_filter to only include tracks from matched playlists."""

        if not self.is_filtered and not include_playlist_info:
            return playlist_tracks_to_filter

        matching_playlist_tracks = self.included_playlists.join(
            playlist_tracks_to_filter,
            how='inner' if include_playlist_info else 'semi',
            on=['playlist.id'])

        if self.excluded_playlists is not None:
            excluded_playlist_tracks = self.excluded_playlists.join(
                playlist_tracks_to_filter, how='inner', on=['playlist.id'])

            matching_playlist_tracks = matching_playlist_tracks.join(
                excluded_playlist_tracks, how='anti', on=['track.id'])

        return matching_playlist_tracks

    def filter_tracks(self, playlist_tracks_to_filter: lf.PlaylistTracks, tracks_to_filter: lf.Tracks) -> lf.Tracks:
        """Filter the specified tracks_to_filter to only include tracks from matched playlists."""
        return self.filter_playlist_tracks(playlist_tracks_to_filter).join(
            tracks_to_filter, how='inner', on=['track.id'])


@dataclass
class PlaylistFilter:
    """Playlist-specific filters."""

    # User-provided parameters
    country: str | list[str] = ''
    dj_name: str = ''
    dj_name_exclude: str = ''
    playlist_include: str = ''
    playlist_exclude: str = ''

    def filter_playlists(self, playlists_to_filter: lf.Playlists) -> PlaylistSet:
        """Filter the specified playlists_to_filter to only include playlists matching this filter."""

        # Parse filters
        match_dj_name = create_text_filter(self.dj_name)
        match_dj_name_exclude = create_text_filter(self.dj_name_exclude)
        match_country = create_text_filter(self.country)
        match_playlist = create_text_filter(self.playlist_include)
        match_excluded_playlist = create_text_filter(self.playlist_exclude)

        # Apply filters to provided data
        has_playlist_filters = False
        matching_playlists = playlists_to_filter

        if match_playlist:
            has_playlist_filters = True
            matching_playlists = matching_playlists.filter(
                match_playlist(pl.col('playlist.name')))

        # Courtesy of Franzi M. (for the country filter suggestion)
        if match_country:
            has_playlist_filters = True
            matching_playlists = matching_playlists.filter(
                match_country(pl.col('playlist.country')))

        if match_dj_name:
            has_playlist_filters = True
            matching_playlists = matching_playlists.filter(
                match_dj_name(pl.col('owner.name').cast(pl.String))
                | match_dj_name(pl.col('owner.id').cast(pl.String)))

        if match_dj_name_exclude:
            has_playlist_filters = True
            matching_playlists = matching_playlists.filter(
                ~match_dj_name_exclude(pl.col('owner.name').cast(pl.String))
                & ~match_dj_name_exclude(pl.col('owner.id').cast(pl.String)))

        # Courtesy of Tobias N. (for the suggestion of the playlist_exclude filter)
        if match_excluded_playlist:
            has_playlist_filters = True
            anti_predicate = match_excluded_playlist(pl.col('playlist.name'))

            # We want to remove tracks that are in these excluded playlists
            # from the result, even when they are present in other matching playlists
            excluded_playlists = self.playlists.filter(anti_predicate)\
                .select('playlist.id')

            # But as an optimization, we also want to avoid including those playlists in the first place.
            matching_playlists = matching_playlists.filter(
                anti_predicate.not_())
        else:
            excluded_playlists = None

        # # Remove everything but the strictly necessary information
        # matching_playlists = matching_playlists.select('playlist.id')

        return PlaylistSet(matching_playlists, excluded_playlists, is_filtered=has_playlist_filters)


@dataclass
class PlaylistTrackSet:
    playlist_tracks: lf.PlaylistTracksWithPlaylist
    is_filtered: bool

    def filter_tracks(self, tracks_to_filter: lf.Tracks, include_playlist_track_info: bool = True) -> lf.Tracks:
        """Filter the specified tracks to only include tracks from playlists in this set."""

        if not self.is_filtered and not include_playlist_track_info:
            return tracks_to_filter

        matching_tracks = self.playlist_tracks.join(
            tracks_to_filter,
            how='inner' if include_playlist_track_info else 'semi',
            on=['track.id'])

        return matching_tracks


@dataclass
class PlaylistTrackFilter:
    """Playlist-membership-specific filters."""

    # User-provided parameters
    added_to_playlist_date: str = ''

    def filter_playlist_tracks(self, playlist_tracks_to_filter: lf.PlaylistTracks) -> PlaylistTrackSet:
        """Filter the specified playlist_tracks_to_filter to only include playlist_tracks matching this filter."""

        # Parse filters
        match_added_to_playlist_date =\
            create_date_filter(self.added_to_playlist_date)

        # Apply filters to provided data
        has_playlist_track_filters = False
        matching_playlist_tracks = playlist_tracks_to_filter

        # Courtesy of Franzi M. (for the added_to_playlist_date filter suggestion)
        if match_added_to_playlist_date:
            has_playlist_track_filters = True
            matching_playlist_tracks = matching_playlist_tracks.filter(
                match_added_to_playlist_date(pl.col('playlist_track.added_at')))

        # Remove everything but the strictly necessary information
        matching_playlist_tracks = matching_playlist_tracks\
            .select('track.id', 'playlist.id', 'playlist.name', 'owner.id', 'owner.name')\
            .group_by('track.id')\
            .agg(pl.col('playlist.id').unique().sort(),
                 pl.col('playlist.name').unique().sort(),
                 pl.col('owner.id').unique().sort(),
                 pl.col('owner.name').unique().sort())

        return PlaylistTrackSet(matching_playlist_tracks, is_filtered=has_playlist_track_filters)


@dataclass
class TrackSet:
    tracks: lf.TracksWithPlaylist
    is_filtered: bool

    def with_extra_columns(self):
        return TrackSet(self.tracks.with_columns(
            pl.col('track.bpm').fill_null(0.0),
            pl.when(pl.col('track.id').is_not_null()).then(pl.concat_str(
                pl.lit('https://open.spotify.com/track/'), 'track.id')).alias('track.url'),
        ), is_filtered=self.is_filtered)

    def filter_playlists(self, playlist_tracks_to_filter: lf.PlaylistTracks, playlists_to_filter: lf.Playlists) -> lf.Playlists:
        """Filter the specified playlists_to_filter to only include playlists that contain at least one track from this set."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered:
            return playlists_to_filter

        matching_playlists = playlists_to_filter.join(
            playlist_tracks_to_filter.join(
                self.tracks, how='semi', on=['track.id']),
            how='semi', on=['playlist.id'])

        return matching_playlists


@dataclass
class TrackFilter:
    """"Track-specific filters."""

    # User-provided parameters
    song_name: str = ''
    song_bpm_range: tuple[int, int] | None = None
    song_release_date: str = ''
    artist_name: str = ''
    artist_is_queer: bool = False
    artist_is_poc: bool = False

    def filter_tracks(self, tracks_to_filter: lf.Tracks,) -> TrackSet:
        """Filter the specified tracks_to_filter to only include tracks matching this filter."""

        # Parse filters
        match_song_name = create_text_filter(self.song_name)
        match_song_release_date = create_date_filter(self.song_release_date)
        match_artist_name = create_text_filter(self.artist_name)

        # Apply filters to provided data
        has_track_filters = False
        matching_tracks = tracks_to_filter

        if match_song_name:
            has_track_filters = True
            matching_tracks = matching_tracks.filter(
                match_song_name(pl.col('track.name')))

        if match_artist_name:
            has_track_filters = True
            matching_tracks = matching_tracks.filter(
                match_artist_name(pl.col('track.artists.name')))

        if self.artist_is_queer:
            has_track_filters = True
            matching_tracks = matching_tracks.filter(
                pl.col('track.artists.is_queer_artist'))

        if self.artist_is_poc:
            has_track_filters = True
            matching_tracks = matching_tracks.filter(
                pl.col('track.artists.is_poc_artist'))

        if self.song_bpm_range:
            has_track_filters = True
            matching_tracks = matching_tracks.filter(
                pl.col('track.bpm').is_null()
                | (pl.col('track.bpm').ge(self.song_bpm_range[0])
                   & pl.col('track.bpm').le(self.song_bpm_range[1])))

        # Courtesy of James B. (for the release_date filter suggestion)
        if match_song_release_date:
            has_track_filters = True
            matching_tracks = matching_tracks.filter(
                match_song_release_date(pl.col('track.album.release_date')))

        return TrackSet(matching_tracks, is_filtered=has_track_filters)


@dataclass
class TrackLyricsSet:
    track_lyrics: lf.TrackLyrics
    is_filtered: bool

    def filter_tracks(self, tracks_to_filter: lf.Tracks, *, include_lyrics: bool = False) -> lf.Tracks:
        """Filter the specified tracks to only include tracks with matching lyrics."""

        # Skip join if it would be a no-op anyway
        if not self.is_filtered and not include_lyrics:
            return tracks_to_filter

        return tracks_to_filter.join(
            self.track_lyrics,
            how='inner' if include_lyrics else 'semi',
            on='track.id')


@dataclass
class TrackLyricsFilter:
    """Lyrics-specific filters."""

    # User-provided parameters
    lyrics_include: str = ''
    lyrics_exclude: str = ''
    lyrics_limit: int | None = None

    def filter_lyrics(self, lyrics_to_filter: lf.TrackLyrics, *, include_matched_lyrics: bool = False) -> TrackLyricsSet:
        """Filter the specified lyrics_to_filter to only include lyrics matching this filter."""

        # Parse filters
        match_lyrics = create_text_filter(self.lyrics_include)
        match_excluded_lyrics = create_text_filter(self.lyrics_exclude)

        # Apply filters to provided data
        has_lyrics_filters = False
        matching_track_lyrics = lyrics_to_filter

        if match_lyrics:
            has_lyrics_filters = True
            matching_track_lyrics = matching_track_lyrics.filter(
                match_lyrics(pl.col('track.lyrics')))

        if match_excluded_lyrics:
            has_lyrics_filters = True
            matching_track_lyrics = matching_track_lyrics.filter(
                ~match_excluded_lyrics(pl.col('track.lyrics')))

        if include_matched_lyrics and match_lyrics:
            matching_track_lyrics = matching_track_lyrics\
                .slice(0, self.lyrics_limit or None)\
                .with_columns(
                    pl.col('track.lyrics')
                    .str.to_lowercase()
                    .str.extract_all('|'.join(self.lyrics_include.lower().split(',')))
                    .list.eval(pl.element().str.to_lowercase())
                    .list.unique()
                    .alias('matched_lyrics'))

        return TrackLyricsSet(matching_track_lyrics, is_filtered=has_lyrics_filters)


class SearchEngine:
    """Encapsulates the logic of filtering for specific songs, playlists etc."""

    playlists: lf.Playlists
    playlist_tracks: lf.PlaylistTracks
    tracks: lf.Tracks
    tracks_adjacent: lf.TracksAdjacent | None = None
    track_lyrics: lf.TrackLyrics | None = None
    countries: list[str]

    def set_data(
        self,
        *,
        playlists: lf.Playlists,
        playlist_tracks: lf.PlaylistTracks,
        tracks: lf.Tracks,
        countries: pl.DataFrame,
        tracks_adjacent: pl.LazyFrame | None = None,
        track_lyrics: pl.LazyFrame | None = None,
    ):
        """Set the source data for the search engine."""
        self.playlists = playlists
        self.playlist_tracks = playlist_tracks
        self.tracks = tracks
        self.tracks_adjacent = tracks_adjacent
        self.track_lyrics = track_lyrics
        self.countries = extract_countries(countries)

    def load_data(self):
        """Load the pre-generated data from the Parquet files."""
        self.playlists = pl.scan_parquet(PLAYLIST_DATA_FILE)
        self.playlist_tracks = pl.scan_parquet(PLAYLIST_TRACKS_DATA_FILE)
        self.tracks = pl.scan_parquet(TRACK_DATA_FILE)
        self.tracks_adjacent = pl.scan_parquet(TRACK_ADJACENT_DATA_FILE)
        self.track_lyrics = pl.scan_parquet(TRACK_LYRICS_DATA_FILE)
        self.countries = extract_countries(pl.read_parquet(COUNTRY_DATA_FILE))

    def get_stats(self) -> tuple[int, int, int, int, int]:
        """Compute statistics about the database content."""
        songs_count, artists_count = count_n_unique(
            self.tracks, ['track.name', 'track.artists.name'])
        playlists_count, djs_count = count_n_unique(
            self.playlists, ['playlist.name', 'owner.name'])
        lyrics_count = count_n_unique(
            self.track_lyrics.join(self.tracks, how='inner', on='track.id'),
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

        #####################
        # Perform filtering #
        #####################

        matching_playlists =\
            playlist_filter.filter_playlists(self.playlists)

        matching_playlist_tracks =\
            playlist_track_filter.filter_playlist_tracks(
                matching_playlists.filter_playlist_tracks(
                    self.playlist_tracks,
                    include_playlist_info=playlist_in_result))

        matching_lyrics =\
            lyrics_filter.filter_lyrics(
                self.track_lyrics,
                include_matched_lyrics=lyrics_in_result)

        matching_tracks =\
            track_filter.filter_tracks(
                matching_lyrics.filter_tracks(
                    matching_playlist_tracks.filter_tracks(
                        self.tracks,
                        include_playlist_track_info=playlist_track_in_result),
                    include_lyrics=lyrics_in_result))

        return matching_tracks.with_extra_columns()\
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
            track_filter.filter_tracks(
                self.tracks)

        if matching_tracks.is_filtered:
            matching_playlists =\
                playlist_filter.filter_playlists(
                    matching_tracks.filter_playlists(
                        self.playlist_tracks, self.playlists))
        else:
            matching_playlists = \
                playlist_filter.filter_playlists(
                    self.playlists)

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
                self.playlists)

        return matching_playlists\
            .filter_tracks(self.playlist_tracks, self.tracks)\
            .group_by('owner.name', 'owner.id').agg(
                pl.n_unique('track.id').alias('song_count'),
                pl.n_unique('track.artists.name').alias('artist_count'),
                pl.n_unique('playlist.name').alias('playlist_count'),
                pl.col('playlist.name').drop_nulls().unique()
                .sort().slice(0, playlist_limit or None),
            ).with_columns(
                pl.when(pl.col('owner.id').is_not_null()).then(pl.concat_str(
                    pl.lit('https://open.spotify.com/user/'), 'owner.id')).alias('owner.url')
            ).sort('playlist_count', descending=True).slice(0, dj_limit or None).collect()

    def find_related_songs(
        self,
        direction: Literal['any', 'prev', 'next'],
        *,
        song_name: str = '',
        artist_name: str = '',
        limit: int | None = 100,
    ) -> tuple[pl.LazyFrame, pl.LazyFrame]:
        """Returns the songs most often played before resp. after the specified song."""

        if self.tracks_adjacent is None:
            raise RuntimeError(
                'self.tracks_adjacent must be initialized to use related track lookup')

        track_filter = TrackFilter(
            song_name=song_name,
            artist_name=artist_name,
        )

        matching_tracks =\
            track_filter.filter_tracks(
                self.tracks)

        def find_adjacent_tracks(starting_tracks, direction: Literal['prev', 'next']):
            if direction == 'next':
                this_song_id = 'pair1.track.id'
                other_song_id = 'pair2.track.id'
            elif direction == 'prev':
                this_song_id = 'pair2.track.id'
                other_song_id = 'pair1.track.id'
            else:
                raise ValueError(f'Invalid value for direction: {direction}')

            return self.tracks_adjacent.join(
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
            self.tracks, how='inner', on='track.id'), is_filtered=True)

        return (matching_tracks.with_extra_columns().tracks.limit(100),
                adjacent_tracks.with_extra_columns()
                .tracks.sort('times_played_together', descending=True)
                .slice(0, limit or None))
