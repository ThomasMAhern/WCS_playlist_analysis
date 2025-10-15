from typing import Final

from utils.search_engine.entity_base import Entity, SubEntity


class Stats(Entity):
    artist_count: Final = "artist_count"
    dj_count: Final = "dj_count"
    playlist_count: Final = "playlist_count"
    song_count: Final = "song_count"


class PlaylistOwner(Entity):
    PREFIX: Final = "owner."
    id: Final = "owner.id"
    name: Final = "owner.name"
    url: Final = "owner.url"


class Playlist(Entity):
    PREFIX: Final = "playlist."
    id: Final = "playlist.id"
    name: Final = "playlist.name"
    region: Final = "playlist.region"
    country: Final = "playlist.country"
    url: Final = "playlist.url"

    matched_terms: Final = "hit_terms"
    matched_terms_count: Final = "hit_count"
    matching_playlist_count: Final = "matching_playlist_count"

    class Owner(SubEntity[PlaylistOwner], PlaylistOwner):
        pass


class Track(Entity):
    PREFIX: Final = "track."
    id: Final = "track.id"
    name: Final = "track.name"
    artists: Final = "track.artists"
    artist_names: Final = "track.artists.name"
    has_queer_artist: Final = "track.artists.is_queer_artist"
    has_poc_artist: Final = "track.artists.is_poc_artist"
    release_date: Final = "track.album.release_date"
    beats_per_minute: Final = "track.bpm"
    region: Final = "track.region"
    country: Final = "track.country"
    url: Final = "track.url"

    pass


class PlaylistTrack(Entity):
    PREFIX: Final = "playlist_track."
    added_at: Final = "playlist_track.added_at"

    class Playlist(SubEntity[Playlist]):
        id: Final = Playlist.id

    class Track(SubEntity[Track]):
        id: Final = Track.id


class TrackAdjacent(Entity):
    times_played_together: Final = "times_played_together"

    class FirstTrack(SubEntity[Track]):
        id: Final = "pair1.track.id"
        name: Final = "pair1.track.name"

    class SecondTrack(SubEntity[Track]):
        id: Final = "pair2.track.id"
        name: Final = "pair2.track.name"


class TrackLyrics(Entity):
    class Track(SubEntity[Track]):
        id: Final = Track.id

    lyrics: Final = "track.lyrics"
    matched_lyrics: Final = "matched_lyrics"
    matched_lyrics_count: Final = "matched_lyrics_count"

    hit_terms: Final = matched_lyrics
    hit_count: Final = matched_lyrics_count
