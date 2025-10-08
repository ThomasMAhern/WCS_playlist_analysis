from typing import Callable
import polars as pl


PLAYLIST_DATA_FILE = 'data_playlist_metadata.parquet'
PLAYLIST_TRACKS_DATA_FILE = 'data_playlist_songs.parquet'
TRACK_DATA_FILE = 'data_song_metadata.parquet'
COUNTRY_DATA_FILE = 'data_countries.parquet'


def extract_countries(countries_dataframe: pl.DataFrame) -> list[str]:
    return countries_dataframe['country'].to_list()


def create_text_filter(filter_expression: str, ascii_case_insensitive: bool = True) -> Callable[[pl.Expr], pl.Expr] | None:
    """Parse a filter expression for a text column."""
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


def count_n_unique(data: pl.LazyFrame, columns: list[str]):
    """Count the number of unique values in the specified columns."""
    return list(data.select(pl.n_unique(columns))
                    .collect(streaming=True)
                    .iter_rows())[0]


class SearchEngine:
    """Encapsulates the logic of filtering for specific songs, playlists etc."""

    playlists: pl.LazyFrame
    playlist_tracks: pl.LazyFrame
    tracks: pl.LazyFrame
    countries: list[str]

    def set_data(self, *, playlists: pl.LazyFrame, playlist_tracks: pl.LazyFrame, tracks: pl.LazyFrame, countries: pl.DataFrame):
        """Set the source data for the search engine."""
        self.playlists = playlists
        self.playlist_tracks = playlist_tracks
        self.tracks = tracks
        self.countries = extract_countries(countries)

    def load_data(self):
        """Load the pre-generated data from the Parquet files."""
        self.playlists = pl.scan_parquet(PLAYLIST_DATA_FILE)
        self.playlist_tracks = pl.scan_parquet(PLAYLIST_TRACKS_DATA_FILE)
        self.tracks = pl.scan_parquet(TRACK_DATA_FILE)
        self.countries = extract_countries(pl.read_parquet(COUNTRY_DATA_FILE))

    def get_stats(self) -> tuple[int, int, int, int]:
        """Compute statistics about the database content."""
        songs_count, artists_count = count_n_unique(
            self.tracks, ['track.name', 'track.artists.name'])
        playlists_count, djs_count = count_n_unique(
            self.playlists, ['playlist.name', 'owner.name'])
        return songs_count, artists_count, playlists_count, djs_count

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
            #
            # Playlist-specific filters
            #
            country: str = '',
            dj_name: str = '',
            dj_name_exclude: str = '',
            playlist_include: str = '',
            playlist_exclude: str = '',
            #
            # Playlist-membership specific filters
            #
            added_to_playlist_date: str = '',
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

        # Track-specific filters
        match_song_name = create_text_filter(song_name)
        match_song_release_date = create_date_filter(song_release_date)
        match_artist_name = create_text_filter(artist_name)

        # Only used for playlist generation
        # playlist_bpm_low: int = 90
        # playlist_bpm_med: int = 95
        # playlist_bpm_high: int = 100

        # Playlist-specific filters
        match_dj_name = create_text_filter(dj_name)
        match_dj_name_exclude = create_text_filter(dj_name_exclude)
        match_country = create_text_filter(country)
        match_playlist = create_text_filter(playlist_include)
        match_excluded_playlist = create_text_filter(playlist_exclude)

        # Playlist-membership-specific filters
        match_added_to_playlist_date = create_date_filter(
            added_to_playlist_date)

        #####################
        # Perform filtering #
        #####################

        # -------------------------------
        # Apply playlist-specific filters
        # -------------------------------

        matching_playlists = self.playlists

        if match_playlist:
            matching_playlists = matching_playlists.filter(
                match_playlist(pl.col('playlist.name')))

        # Courtesy of Franzi M. (for the country filter suggestion)
        if match_country:
            matching_playlists = matching_playlists.filter(
                match_country(pl.col('playlist.country')))

        if match_dj_name:
            matching_playlists = matching_playlists.filter(
                match_dj_name(pl.col('owner.name').cast(pl.String))
                | match_dj_name(pl.col('owner.id').cast(pl.String)))

        if match_dj_name_exclude:
            matching_playlists = matching_playlists.filter(
                ~match_dj_name_exclude(pl.col('owner.name').cast(pl.String))
                & ~match_dj_name_exclude(pl.col('owner.id').cast(pl.String)))

        # Courtesy of Tobias N. (for the suggestion of the playlist_exclude filter)
        if match_excluded_playlist:
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

        # ------------------------------------------
        # Apply playlist-membership-specific filters
        # ------------------------------------------

        matching_playlist_tracks = matching_playlists.join(
            self.playlist_tracks, how='inner', on=['playlist.id'])

        if excluded_playlists is not None:
            excluded_playlist_tracks = excluded_playlists.join(
                self.playlist_tracks, how='inner', on=['playlist.id'])

            matching_playlist_tracks = matching_playlist_tracks.join(
                excluded_playlist_tracks, how='anti', on=['track.id'])

        # Courtesy of Franzi M. (for the added_to_playlist_date filter suggestion)
        if match_added_to_playlist_date:
            matching_playlist_tracks = matching_playlist_tracks.filter(
                match_added_to_playlist_date(pl.col('playlist_track.added_at')))

        # Remove everything but the strictly necessary information
        matching_playlist_tracks = matching_playlist_tracks\
            .select('track.id', 'playlist.name', 'owner.name')\
            .group_by('track.id')\
            .agg(pl.col('playlist.name').unique().sort(), pl.col('owner.name').unique().sort())

        # ----------------------------
        # Apply track-specific filters
        # ----------------------------

        matching_tracks = matching_playlist_tracks.join(
            self.tracks, how='inner', on=['track.id'])

        if match_song_name:
            matching_tracks = matching_tracks.filter(
                match_song_name(pl.col('track.name')))

        if match_artist_name:
            matching_tracks = matching_tracks.filter(
                match_artist_name(pl.col('track.artists.name')))

        if artist_is_queer:
            matching_tracks = matching_tracks.filter(
                pl.col('track.artists.is_queer_artist'))

        if artist_is_poc:
            matching_tracks = matching_tracks.filter(
                pl.col('track.artists.is_poc_artist'))

        if song_bpm_range:
            matching_tracks = matching_tracks.filter(
                pl.col('track.bpm').is_null()
                | (pl.col('track.bpm').ge(song_bpm_range[0])
                   & pl.col('track.bpm').le(song_bpm_range[1])))

        # Courtesy of James B. (for the release_date filter suggestion)
        if match_song_release_date:
            matching_tracks = matching_tracks.filter(
                match_song_release_date(pl.col('track.album.release_date')))

        return matching_tracks.with_columns(
            pl.col('track.bpm').fill_null(0.0),
            pl.when(pl.col('track.id').is_not_null()).then(pl.concat_str(
                pl.lit('https://open.spotify.com/track/'), 'track.id')).alias('track.url'),
        ).slice(skip_num_top_results, limit or None)

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

        # Track-specific filters
        match_song_name = create_text_filter(song_name)
        match_artist_name = create_text_filter(artist_name)

        # Playlist-specific filters
        match_dj_name = create_text_filter(dj_name)
        match_country = create_text_filter(country)
        match_playlist = create_text_filter(playlist_include)
        match_excluded_playlist = create_text_filter(playlist_exclude)

        #####################
        # Perform filtering #
        #####################

        # ----------------------------
        # Apply track-specific filters
        # ----------------------------

        has_tracks_filter = False
        matching_tracks = self.tracks

        if match_song_name:
            has_tracks_filter = True
            matching_tracks = matching_tracks.filter(
                match_song_name(pl.col('track.name')))

        if match_artist_name:
            has_tracks_filter = True
            matching_tracks = matching_tracks.filter(
                match_artist_name(pl.col('track.artists.name')))

        # -------------------------------
        # Apply playlist-specific filters
        # -------------------------------

        matching_playlists = self.playlists

        if has_tracks_filter:
            matching_playlists = matching_playlists.join(
                self.playlist_tracks.join(
                    matching_tracks, how='semi', on=['track.id']),
                how='semi', on=['playlist.id'])

        if match_playlist:
            matching_playlists = matching_playlists.filter(
                match_playlist(pl.col('playlist.name')))

        # Courtesy of Franzi M. (for the country filter suggestion)
        if match_country:
            matching_playlists = matching_playlists.filter(
                match_country(pl.col('playlist.country')))

        if match_dj_name:
            matching_playlists = matching_playlists.filter(
                match_dj_name(pl.col('owner.name').cast(pl.String))
                | match_dj_name(pl.col('owner.id').cast(pl.String)))

        if match_excluded_playlist:
            matching_playlists = matching_playlists.filter(
                match_excluded_playlist(pl.col('playlist.name')).not_())

        return matching_playlists.with_columns(
            pl.when(pl.col('playlist.id').is_not_null()).then(pl.concat_str(
                pl.lit('https://open.spotify.com/track/'), 'playlist.id')).alias('playlist.url'),
            pl.when(pl.col('owner.id').is_not_null()).then(pl.concat_str(
                pl.lit('https://open.spotify.com/user/'), 'owner.id')).alias('owner.url')
        ).slice(0, limit or None)

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

        match_dj_name = create_text_filter(dj_name)
        match_playlist = create_text_filter(playlist_name)

        #####################
        # Perform filtering #
        #####################

        matching_playlists = self.playlists

        if match_playlist:
            matching_playlists = matching_playlists.filter(
                match_playlist(pl.col('playlist.name')))

        if match_dj_name:
            matching_playlists = matching_playlists.filter(
                match_dj_name(pl.col('owner.name').cast(pl.String))
                | match_dj_name(pl.col('owner.id').cast(pl.String)))

        return matching_playlists.join(
            self.playlist_tracks, how='inner', on=['playlist.id']
        ).join(
            self.tracks, how='inner', on=['track.id']
        ).with_columns(
            pl.when(pl.col('owner.id').is_not_null()).then(pl.concat_str(
                pl.lit('https://open.spotify.com/user/'), 'owner.id')).alias('owner.url')
        ).group_by('owner.name', 'owner.url').agg(
            pl.n_unique('track.id').alias('song_count'),
            pl.n_unique('track.artists.name').alias('artist_count'),
            pl.n_unique('playlist.name').alias('playlist_count'),
            pl.col('playlist.name').drop_nulls().unique()
            .sort().slice(0, playlist_limit or None),
        ).sort('playlist_count', descending=True).slice(0, dj_limit or None)
