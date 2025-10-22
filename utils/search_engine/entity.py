from typing import Final

import polars as pl

from utils.common.entities import Entity, SubEntity, field


class Stats(Entity):
    artist_count: Final = field("artist_count", pl.UInt32)
    """
    The number of artists. Depending on the context, this can mean:

    1. The number of unique artists contained in a playlist.
    2. The number of unique artists contained in a DJ's playlists.
    3. The number of unique artists played in a certain region/country.
    """

    dj_count: Final = field("dj_count", pl.UInt32)
    """
    The number of DJs. Depending on the context, this can mean:

    1. The number of DJs that have this song in
       at least one of their playlists
    2. The number of DJs in a region/country.
    """

    playlist_count: Final = field("playlist_count", pl.UInt32)
    """
    The number of playlists. Depending on the context, this can mean:

    1. The number of playlists a song is in.
    2. The number of playlists a DJ has.
    3. The number of playlists in a certain region/country.
    """

    song_count: Final = field("song_count", pl.UInt32)
    """
    The number of (unique) songs. Depending on the context, this can mean:

    1. The number of (unique) songs in a playlist.
    2. The number of (unique) songs in a DJ's playlists.
    3. The number of songs played in a certain region/country.
    """


class PlaylistOwner(Entity):
    """Represents a DJ who owns one or more playlists."""

    PREFIX: Final = "owner."
    """Common prefix for `PlaylistOwner` columns."""

    id: Final = field("owner.id", pl.String)
    """The Spotify User ID of the playlist's owner."""

    url: Final = field("owner.url", pl.String)
    """The Spotify User URL of the playlist's owner."""

    name: Final = field("owner.name", pl.String)
    """The name of the playlist's owner."""

    region: Final = field("owner.region", pl.Categorical)
    """
    The name of the world region a DJ is associated with.

    This is currently based on a manually curated dataset
    assigning DJs to their home regions/home countries.
    """

    country: Final = field("owner.country", pl.Categorical)
    """
    The name of the country a DJ is associated with.

    This is currently based on a manually curated dataset
    assigning DJs to their home regions/home countries.
    """

    is_wcs_dj: Final = field("owner.is_wcs_dj", pl.Boolean)
    """
    Whether this Spotify profile is known to belong to an actual WCS DJ.

    This is currently based on a manually curated dataset.
    """


class Playlist(Entity):
    """Represents a playlist (as retrieved from Spotify or from other sources)."""

    PREFIX: Final = "playlist."
    """Common prefix for `Playlist` columns."""

    id: Final = field("playlist.id", pl.String)
    """The Spotify ID of the playlist."""

    url: Final = field("playlist.url", pl.String)
    """The Spotify URL of the playlist."""

    name: Final = field("playlist.name", pl.String)
    """The name of the playlist."""

    extracted_dates: Final = field('playlist.extracted_date', pl.List(pl.List(pl.String)))
    """The list of possible date strings extracted from a playlist's name."""

    is_social_set: Final = field("playlist.is_social_set", pl.Boolean)
    """
    Whether this playlist likely represents an actual DJ set
    that was played (or is going to be played) at an event/party.
    """

    region: Final = field("playlist.region", pl.List(pl.Categorical))
    """
    The name of the world region a playlist (resp.
    the playlist's owner) is associated with.

    This is currently based on a manually curated dataset
    assigning DJs to their home regions/home countries.
    """

    country: Final = field("playlist.country", pl.List(pl.Categorical))
    """
    The name of the country a playlist (resp.
    the playlist's owner) is associated with.

    This is currently based on a manually curated dataset
    assigning DJs to their home regions/home countries.
    """

    matched_terms: Final = field("hit_terms", pl.List(pl.String))
    """The list of terms in the playlist's name that match the search query."""

    matched_terms_count: Final = field("hit_count", pl.UInt32)
    """The number of terms in the playlist's name that match the search query."""

    matching_playlist_count: Final = field("matching_playlist_count", pl.UInt32)
    """The number of playlists this track is in that also matched the search query."""

    matching_song_count: Final = field("matching_song_count", pl.UInt32)
    """The number of songs in this playlist that matched the search query."""

    class Owner(SubEntity[PlaylistOwner], PlaylistOwner):
        """Represents the owner of a playlist."""
        pass


class Track(Entity):
    PREFIX: Final = "track."
    """Common prefix for `Track` columns."""

    id: Final = field("track.id", pl.String)
    """The Spotify ID of the song (`pl.String`)."""

    url: Final = field("track.url", pl.String)
    """The Spotify URL of the song."""

    name: Final = field("track.name", pl.String)
    """The name of the song."""

    artists: Final = field("track.artists", pl.List(pl.String))
    """The song's artists, represented as a list of artist names."""

    artist_names: Final = field("track.artists.name", pl.String)
    """The song's artist, represented as a single string."""

    has_queer_artist: Final = field("track.artists.is_queer_artist", pl.Boolean)
    """Whether any of the song's artist is known to be queer."""

    has_poc_artist: Final = field("track.artists.is_poc_artist", pl.Boolean)
    """Whether any of the song's artist is known to be be POC."""

    release_date: Final = field("track.album.release_date", pl.Date)
    """The song's release date."""

    beats_per_minute: Final = field("track.bpm", pl.Float64)
    """The song's tempo given as beats per minute."""

    region: Final = field("track.region", pl.List(pl.Categorical))
    """The list of world regions where a given track has been played."""

    country: Final = field("track.country", pl.List(pl.Categorical))
    """The list of countries where a given track has been played."""


class PlaylistTrack(Entity):
    PREFIX: Final = "playlist_track."
    """Common prefix for `PlaylistTrack` columns."""

    number: Final = field("playlist_track.number", pl.UInt16)
    """The index of this entry within the playlist."""

    added_at: Final = field("playlist_track.added_at", pl.Date)
    """The date when this entry was added to the playlist."""

    class Playlist(SubEntity[Playlist]):
        id: Final = Playlist.id

    class Track(SubEntity[Track]):
        id: Final = Track.id


class TrackAdjacent(Entity):
    times_played_together: Final = "times_played_together"

    class FirstTrack(SubEntity[Track]):
        id: Final = Track.id.alias("pair1.track.id")
        name: Final = Track.name.alias("pair1.track.name")
        artists: Final = Track.name.alias("pair1.track.artists")

    class SecondTrack(SubEntity[Track]):
        id: Final = Track.id.alias("pair2.track.id")
        name: Final = Track.name.alias("pair2.track.name")
        artists: Final = Track.artists.alias("pair2.track.artists")


class TrackLyrics(Entity):
    class Track(SubEntity[Track]):
        id: Final = Track.id

    lyrics: Final = field("track.lyrics", pl.String)
    """The full lyrics of a song."""

    matched_lyrics: Final = field("matched_lyrics", pl.List(pl.String))
    """The list of terms in the lyrics that match the search query."""

    matched_lyrics_count: Final = field("matched_lyrics_count", pl.UInt32)
    """The number of unique terms in the lyrics that match the search query."""
