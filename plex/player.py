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

from plex.api import Api
from plex.constants import PLEX_PROTOCOL, PLEX_PLAYER_PLAYING, \
        PLEX_PLAYER_PAUSED, PLEX_PLAYER_STOPPED, \
        SETTINGS_PROVIDER_PLAYBACK_ENABLE_EXTERNAL_SUBTITLES
from plex.server import Server

from lib.utils import log, mediaProvider2str, toMilliseconds, localise

REPORTING_INTERVAL = 5 # seconds

SUBTITLE_UNKNOWN = localise(32064)


class Player(xbmc.Player):
    def __init__(self):
        '''Initializes the player'''
        super(Player, self).__init__()

        self._providers = {}
        self._lock = threading.Lock()

        self._state = {'playbacktime': None, 'state': None, 'lastreport': None}


    def AddProvider(self, mediaProvider):
        '''Adds a media provider to the player'''
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        with self._lock:
            self._providers[mediaProvider.getIdentifier()] = mediaProvider


    def RemoveProvider(self, mediaProvider):
        '''Removes the associated media provider'''
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        with self._lock:
            del self._providers[mediaProvider.getIdentifier()]


    def Process(self):
        '''Called from the observer thread to periodically report the state to PMS'''
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
        '''Triggered when xbmc.Player is started'''
        with self._lock:
            self._reset()
            self._getPlayingFile()


    def onAVStarted(self):
        '''Triggered when playback actually starts'''
        with self._lock:
            self._startPlayback()
            self._syncPlaybackState(playbackTime=self._getPlayingTime(), state=PLEX_PLAYER_PLAYING)


    def onPlayBackSeek(self, time, seekOffset):
        '''Triggered when seeking.'''
        with self._lock:
            self._syncPlaybackState(playbackTime=self._getPlayingTime())


    def onPlayBackSeekChapter(self, chapter):
        '''Triggered when seeking chapters.'''
        with self._lock:
            self._syncPlaybackState(playbackTime=self._getPlayingTime())


    def onPlayBackPaused(self):
        '''Triggered when playback is paused.'''
        with self._lock:
            self._syncPlaybackState(playbackTime=self._getPlayingTime(), state=PLEX_PLAYER_PAUSED)


    def onPlayBackResumed(self):
        '''Triggered when playback is resumed after a pause'''
        with self._lock:
            self._syncPlaybackState(playbackTime=self._getPlayingTime(), state=PLEX_PLAYER_PLAYING)


    def onPlayBackStopped(self):
        '''Triggered when playback is stopped'''
        with self._lock:
            self._playbackEnded()


    def onPlayBackEnded(self):
        '''Triggered when playback ends. Resets the player state and inherently kills the reporting loop'''
        with self._lock:
            self._playbackEnded()


    def _getPlayingFile(self):
        '''Fill the playing file in the respective member variable with a lock'''
        if self.isPlaying():
            self._file = self.getPlayingFile()


    def _playbackEnded(self):
        '''Sends stop state to Plex and resets the player member variables'''
        self._syncPlaybackState(state=PLEX_PLAYER_STOPPED)
        self._reset()


    def _startPlayback(self):
        '''Identifies the item (if from Plex) and initializes the player state'''
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
            log('currently playing item {} ({}) has been imported from an unknown media provider {}' \
                .format(playingItem.getLabel(), self._file, mediaProviderId), xbmc.LOGWARNING)
            return
        self._mediaProvider = self._providers[mediaProviderId]

        videoInfoTag = self.getVideoInfoTag()
        if not videoInfoTag:
            return

        itemId = videoInfoTag.getUniqueID(PLEX_PROTOCOL)
        if not itemId:
            return

        if not itemId.isdigit():
            log('invalid item id plex://{} (non digit). Kodi will not report playback state to Plex Media Server' \
                    .format(itemId), xbmc.LOGERROR)
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
                log('failed to load settings for {} ({}) playing from {}' \
                    .format(self._item.title, self._file, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
                self._reset()
                return

            # load external subtitles
            if settings.getBool(SETTINGS_PROVIDER_PLAYBACK_ENABLE_EXTERNAL_SUBTITLES):
                self._addExternalSubtitles(plexServer.PlexServer())

        else:
            self._reset()


    def _addExternalSubtitles(self, plexServer):
        '''Add external subtitles to the player'''
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
                log('external subtitle "{}" [{}] at index {} added for "{}" ({}) from media provider {}' \
                    .format(
                        subtitle.title,
                        subtitle.language,
                        subtitle.index,
                        self._item.title,
                        self._file,
                        mediaProvider2str(self._mediaProvider)
                    )
                )


    def _syncPlaybackState(self, state=None, playbackTime=None):
        '''Syncs last available state and publishes to PMS'''
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


    def _getPlayingTime(self):
        '''Gets current xbmc.Player time in miliseconds'''
        return toMilliseconds(self.getTime())


    def _reset(self):
        '''Resets player member variables to default'''
        # Player item
        self._file = None
        self._item = None
        self._itemId = None
        self._mediaProvider = None
        self._duration = None
        # Player last known state
        self._state = {'playbackTime': None, 'state': None, 'lastreport': None}
