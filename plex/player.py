#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#
import time
import threading

import xbmc
import xbmcmediaimport

from plexapi.server import PlexServer
from plex.api import Api
from plex.constants import (
    PLEX_PROTOCOL,
    PLEX_PLAYER_PLAYING,
    PLEX_PLAYER_PAUSED,
    PLEX_PLAYER_STOPPED,
    SETTINGS_PROVIDER_PLAYBACK_ENABLE_EXTERNAL_SUBTITLES
)
from plex.server import Server

from lib.utils import log, mediaProvider2str, toMilliseconds, localize

REPORTING_INTERVAL = 5  # seconds

SUBTITLE_UNKNOWN = localize(32064)


class Player(xbmc.Player):
    """Class with customization of the xmbc Player class to handle working with Plex"""
    def __init__(self):
        """Initializes the player"""
        super(Player, self).__init__()

        self._providers = {}
        self._lock = threading.Lock()

        self._state = {'playbacktime': 0, 'state': None, 'lastreport': 0}

    def AddProvider(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Adds a media provider to the player

        :param mediaProvider: Media provider to add to the player
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        with self._lock:
            self._providers[mediaProvider.getIdentifier()] = mediaProvider

    def RemoveProvider(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Removes a media provider from the player

        :param mediaProvider: Media provider to remove from the player
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        with self._lock:
            del self._providers[mediaProvider.getIdentifier()]

    def Process(self):
        """Report the state of the player to the Plex server, periodically called by observer thread"""
        with self._lock:
            if self.isPlaying():
                lastreport = self._state.get('lastreport')

                if not lastreport:
                    return

                if (time.time() - lastreport) < REPORTING_INTERVAL:
                    return

                if self._item:
                    self._syncPlaybackState(playbackTime=self._getPlayingTime())

    def onPlayBackStarted(self):
        """Event handler: triggered when the player is started"""
        with self._lock:
            self._reset()
            self._getPlayingFile()

    def onAVStarted(self):
        """Event handler: triggered when the playback actually starts"""
        with self._lock:
            self._startPlayback()
            self._syncPlaybackState(playbackTime=self._getPlayingTime(), state=PLEX_PLAYER_PLAYING)

    def onPlayBackSeek(self, time, seekOffset):
        """Event handler: triggered when seeking through the video"""
        with self._lock:
            self._syncPlaybackState(playbackTime=self._getPlayingTime())

    def onPlayBackSeekChapter(self, chapter):
        """Event handler: triggered when the seeking chapters"""
        with self._lock:
            self._syncPlaybackState(playbackTime=self._getPlayingTime())

    def onPlayBackPaused(self):
        """Event handler: triggered when the playback is paused"""
        with self._lock:
            self._syncPlaybackState(playbackTime=self._getPlayingTime(), state=PLEX_PLAYER_PAUSED)

    def onPlayBackResumed(self):
        """Event handler: triggered when the playback is resumed after a pause"""
        with self._lock:
            self._syncPlaybackState(playbackTime=self._getPlayingTime(), state=PLEX_PLAYER_PLAYING)

    def onPlayBackStopped(self):
        """Event handler: triggered when playback is stopped"""
        with self._lock:
            self._playbackEnded()

    def onPlayBackEnded(self):
        """Event handler: Triggered when playback ends. Resets player state and inherently kills the reporting loop"""
        with self._lock:
            self._playbackEnded()

    def _getPlayingFile(self):
        """Fill the playing file in the respective member variable with a lock"""
        if self.isPlaying():
            self._file = self.getPlayingFile()

    def _playbackEnded(self):
        """Sends stop state to Plex and resets the player member variables"""
        self._syncPlaybackState(state=PLEX_PLAYER_STOPPED)
        self._reset()

    def _startPlayback(self):
        """Identifies the item (if from Plex) and initializes the player state"""
        if not self._file:
            return

        if not self.isPlayingVideo():
            return

        playingItem = self.getPlayingItem()
        if not playingItem:
            return

        # check if the item has been imported from a media provider
        mediaProviderId = playingItem.getMediaProviderId()
        if not mediaProviderId:
            return

        if not mediaProviderId in self._providers:
            log(
                (
                    f"currently playing item {playingItem.getLabel()} ({self._file}) "
                    f"has been imported from an unknown media provider {mediaProviderId}"
                ),
                xbmc.LOGWARNING
            )
            return
        self._mediaProvider = self._providers[mediaProviderId]

        videoInfoTag = self.getVideoInfoTag()
        if not videoInfoTag:
            return

        itemId = videoInfoTag.getUniqueID(PLEX_PROTOCOL)
        if not itemId:
            return

        if not itemId.isdigit():
            log(
                f"Item id is not a digit: plex://{itemId}. Kodi will not report playback state to Plex Media Server",
                xbmc.LOGERROR
            )
            return

        self._itemId = int(itemId)

        if self._mediaProvider:
            # save item
            plexServer = Server(self._mediaProvider)
            self._item = Api.getPlexItemDetails(
                plexServer.PlexServer(),
                self._itemId,
                Api.getPlexMediaClassFromMediaType(videoInfoTag.getMediaType())
            )
            self._duration = toMilliseconds(self.getTotalTime())

            # register settings
            settings = self._mediaProvider.prepareSettings()
            if not settings:
                log(
                    (
                        f"failed to load settings for {self._item.title} ({self._file}) "
                        f"playing from {mediaProvider2str(self._mediaProvider)}"
                    ),
                    xbmc.LOGWARNING
                )
                self._reset()
                return

            # load external subtitles
            if settings.getBool(SETTINGS_PROVIDER_PLAYBACK_ENABLE_EXTERNAL_SUBTITLES):
                self._addExternalSubtitles(plexServer.PlexServer())

        else:
            self._reset()

    def _addExternalSubtitles(self, plexServer: PlexServer):
        """Add external subtitles to the player

        :param plexServer: Plex server to get subtitles from
        :type plexServer: :class:`PlexServer`
        """
        if not self._item:
            return

        # note: internal subtitles don't have a key provided by plexapi
        external_subtitles = [sub for sub in self._item.subtitleStreams() if sub.key]
        if external_subtitles:
            for subtitle in external_subtitles:
                # TODO: What to do with forced subs?
                self.addSubtitle(
                    plexServer.url(subtitle.key, includeToken=True),
                    subtitle.title if subtitle.title else SUBTITLE_UNKNOWN,
                    subtitle.language if subtitle.language else SUBTITLE_UNKNOWN,
                    subtitle.selected
                )
                log(
                    (
                        f"external subtitle '{subtitle.title}' [{subtitle.language}]"
                        f"at index {subtitle.index} added for '{self._item.title}' ({self._file})"
                        f"from media provider {mediaProvider2str(self._mediaProvider)}"
                    ),
                    xbmc.LOGINFO
                )

    def _syncPlaybackState(self, state: str = None, playbackTime: float = None):
        """Syncs last available state and playback time then publishes to PMS

        :param state: Current state of playback in the player (playing, paused, stopped)
        :type state: str
        :param playbackTime: Amount of time in milliseconds playback is into the video
        :type playbackTime: float
        """
        # either update state or time
        if not state and not playbackTime:
            return

        # sane check
        if not self._item:
            return

        if state:
            self._state['state'] = state

        if playbackTime is not None:
            self._state['playbackTime'] = int(playbackTime)

        # Send update to PMS and update last report timestamp
        if self._state.get('playbackTime') is not None and self._state.get('state'):
            self._state['lastreport'] = time.time()
            self._item.updateTimeline(
                self._state['playbackTime'],
                state=self._state['state'],
                duration=self._duration
            )

    def _getPlayingTime(self) -> float:
        """Gets current xbmc.Player time in miliseconds"""
        return toMilliseconds(self.getTime())

    def _reset(self):
        """Resets player member variables to default"""
        # Player item
        self._file = None
        self._item = None
        self._itemId = None
        self._mediaProvider = None
        self._duration = None
        # Player last known state
        self._state = {'playbackTime': 0, 'state': None, 'lastreport': 0}
