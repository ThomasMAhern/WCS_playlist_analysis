from enum import StrEnum


class FilterOrder(StrEnum):
    Playlists_First = 'playlists_first'
    PlaylistsAndTracks_First = 'playlists_and_tracks_first'


class FilterType(StrEnum):
    Playlist = 'playlist'
    PlaylistTrack = 'playlist_track'
    Track = 'track'
    Lyrics = 'lyrics'
