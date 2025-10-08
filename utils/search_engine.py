import polars as pl


PLAYLIST_DATA_FILE = 'data_playlist_metadata.parquet'
PLAYLIST_TRACKS_DATA_FILE = 'data_playlist_songs.parquet'
TRACK_DATA_FILE = 'data_song_metadata.parquet'
COUNTRY_DATA_FILE = 'data_countries.parquet'


def extract_countries(countries_dataframe: pl.DataFrame) -> list[str]:
    return countries_dataframe['country'].to_list()


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

    def find_songs(
            self,
            *,
            #
            # Track-specific filters
            #
            song_name: str = '',
            song_bpm_range: tuple[int, int] = (0, 150),
            song_release_date: str = '',
            artist_name: str = '',
            artist_is_queer: bool = False,
            artist_is_poc: bool = False,
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
            skip_num_top_results: int = 0,
            limit: int | None = None,
    ) -> pl.LazyFrame:
        #####################
        # Filter parameters #
        #####################

        # Track-specific filters
        song_inputs: list[str] = list(
            filter(bool, song_name.strip().lower().split(',')))
        song_release_dates: list[str] = list(
            filter(bool, song_release_date.strip().split(',')))
        artist_inputs: list[str] = list(
            filter(bool, artist_name.strip().lower().split(',')))

        # Only used for playlist generation
        # playlist_bpm_low: int = 90
        # playlist_bpm_med: int = 95
        # playlist_bpm_high: int = 100

        # Playlist-specific filters
        dj_names: list[str] = list(
            filter(bool, dj_name.strip().lower().split(',')))
        playlist_inputs: list[str] = list(
            filter(bool, playlist_include.strip().lower().split(',')))
        anti_playlist_inputs: list[str] = list(filter(bool, playlist_exclude
                                                      .strip().lower().split(',')))

        # Playlist-membership specific filters
        added_to_playlist_date_input: str = ''

        added_to_playlist_dates = list(
            filter(bool, added_to_playlist_date_input.strip().split(',')))

        #####################
        # Perform filtering #
        #####################

        # -------------------------------
        # Apply playlist-specific filters
        # -------------------------------

        matching_playlists = self.playlists

        if playlist_inputs:
            matching_playlists = matching_playlists.filter(
                pl.col('playlist.name').str.contains_any(playlist_inputs, ascii_case_insensitive=True))

        if country:
            matching_playlists = matching_playlists.filter(
                pl.col('playlist.country').str.contains_any([country], ascii_case_insensitive=True))

        if dj_name:
            matching_playlists = matching_playlists.filter(
                pl.col('owner.name').cast(pl.String)
                .str.contains_any(dj_name, ascii_case_insensitive=True)
                | pl.col('owner.id').cast(pl.String).str.contains_any(dj_name, ascii_case_insensitive=True))

        if playlist_exclude:
            anti_predicate = pl.col('playlist.name').str.contains_any(
                anti_playlist_inputs, ascii_case_insensitive=True)

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

        if anti_playlist_inputs:
            excluded_playlist_tracks = excluded_playlists.join(
                self.playlist_tracks, how='inner', on=['playlist.id'])

            matching_playlist_tracks = matching_playlist_tracks.join(
                excluded_playlist_tracks, how='anti', on=['track.id'])

        # Courtesy of Franzi M. (for the added_to_playlist_date filter suggestion)
        if added_to_playlist_dates:
            matching_playlist_tracks = matching_playlist_tracks.filter(
                pl.col('playlist_track.added_at').dt.to_string()
                .str.contains_any(added_to_playlist_dates, ascii_case_insensitive=True))

        # Remove everything but the strictly necessary information
        matching_playlist_tracks = matching_playlist_tracks\
            .select('track.id', 'playlist.name')\
            .group_by('track.id')\
            .agg(pl.col('playlist.name'))

        # ----------------------------
        # Apply track-specific filters
        # ----------------------------

        matching_tracks = matching_playlist_tracks.join(
            self.tracks, how='inner', on=['track.id'])

        if song_inputs:
            matching_tracks = matching_tracks.filter(
                pl.col('track.name').str.contains_any(song_inputs, ascii_case_insensitive=True))

        if artist_inputs:
            matching_tracks = matching_tracks.filter(
                pl.col('track.artists.name').str.contains_any(artist_inputs, ascii_case_insensitive=True))

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
        if song_release_dates:
            matching_tracks = matching_tracks.filter(
                pl.col('track.album.release_date').dt.to_string().str.contains_any(
                    song_release_dates, ascii_case_insensitive=True))

        return matching_tracks.slice(skip_num_top_results, limit or None)
