#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#
import time
import threading

import xbmc  # pylint: disable=import-error
from xbmcaddon import Settings  # pylint: disable=import-error
import xbmcmediaimport  # pylint: disable=import-error

from plexapi.video import Episode
from plexapi.server import PlexServer
from plex.api import Api
from plex.constants import (
    PLEX_PROTOCOL,
    PLEX_PLAYER_PLAYING,
    PLEX_PLAYER_PAUSED,
    PLEX_PLAYER_STOPPED,
    SETTINGS_IMPORT_PLAYBACK_SKIP_INTRO,
    SETTINGS_IMPORT_PLAYBACK_SKIP_ADS,
    SETTINGS_IMPORT_PLAYBACK_SKIP_ASK,
    SETTINGS_IMPORT_PLAYBACK_SKIP_ALWAYS,
    SETTINGS_IMPORT_PLAYBACK_SKIP_NEVER,
    SETTINGS_PROVIDER_PLAYBACK_ENABLE_EXTERNAL_SUBTITLES
)
from plex.server import Server
from plex.skip_dialog import SkipDialog

from lib.utils import log, mediaProvider2str, milliToSeconds, toMilliseconds, localize

PROCESSING_INTEREVAL = 1  # seconds
REPORTING_INTERVAL = 5  # seconds

SUBTITLE_UNKNOWN = localize(32064).decode()


class Player(xbmc.Player):
    """Class with customization of the xmbc Player class to handle working with Plex"""
    def __init__(self):
        """Initializes the player"""
        super(Player, self).__init__()

        self._providers = {}
        self._lock = threading.Lock()
        self._lastProcessing = 0

        self._state = {'playbacktime': 0, 'state': None, 'lastreport': 0}
        self._duration = None
        self._introMarker = None
        self._adMarkers = []
        self._skipIntroSetting = SETTINGS_IMPORT_PLAYBACK_SKIP_NEVER
        self._skipAdsSetting = SETTINGS_IMPORT_PLAYBACK_SKIP_NEVER
        self._skipDialog = None

        self._file = None
        self._item = None
        self._itemId = None
        self._mediaProvider = None
        self._mediaImport = None

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
                currentTime = time.time()
                if (currentTime - self._lastProcessing) < PROCESSING_INTEREVAL:
                    return

                self._processPlayback()
                self._lastProcessing = currentTime

                lastreport = self._state.get('lastreport')

                if not lastreport:
                    return

                if (currentTime - lastreport) < REPORTING_INTERVAL:
                    return

                if self._item:
                    self._syncPlaybackState(playbackTime=self._getPlayingTime())

    def onPlayBackStarted(self):
        """Event handler: triggered when the player is started"""
        with self._lock:
            self._reset()
            try:
                self._file = self.getPlayingFile()
            except RuntimeError:
                pass

    def onAVStarted(self):
        """Event handler: triggered when the playback actually starts"""
        with self._lock:
            self._startPlayback()
            self._syncPlaybackState(playbackTime=self._getPlayingTime(), state=PLEX_PLAYER_PLAYING)

    def onPlayBackSeek(self, seekTime, seekOffset):  # pylint: disable=unused-argument
        """Event handler: triggered when seeking through the video"""
        with self._lock:
            self._syncPlaybackState(playbackTime=self._getPlayingTime())

    def onPlayBackSeekChapter(self, chapter):  # pylint: disable=unused-argument
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

        if mediaProviderId not in self._providers:
            log(
                (
                    f"currently playing item {playingItem.getLabel()} ({self._file}) "
                    f"has been imported from an unknown media provider {mediaProviderId}"
                ),
                xbmc.LOGWARNING
            )
            return

        self._mediaProvider = self._providers[mediaProviderId]
        if not self._mediaProvider:
            return

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

        # save item
        plexServer = Server(self._mediaProvider)
        self._item = Api.getPlexItemDetails(
            plexServer.PlexServer(),
            self._itemId,
            Api.getPlexMediaClassFromMediaType(videoInfoTag.getMediaType())
        )
        if not self._item:
            log(
                (
                    f"failed to retrieve details for item {self._itemId} ({self._file}) "
                    f"playing from {mediaProvider2str(self._mediaProvider)}"
                ),
                xbmc.LOGWARNING
            )
            self._reset()
            return

        self._duration = toMilliseconds(self.getTotalTime())

        # handle any provider specific settings
        self._handleProviderSettings(plexServer.PlexServer())

        # get the matching media import
        self._mediaImport = self._mediaProvider.getImportByMediaType(videoInfoTag.getMediaType())
        if self._mediaImport:
            # handle any import specific settings
            self._handleImportSettings()
        else:
            log(
                (
                    f"failed to determine import for {self._item.title} ({self._file}) "
                    f"playing from {mediaProvider2str(self._mediaProvider)}"
                ),
                xbmc.LOGWARNING
            )

    def _handleProviderSettings(self, plexServer: PlexServer):
        # load provider settings
        providerSettings = self._mediaProvider.prepareSettings()
        if not providerSettings:
            log(
                (
                    f"failed to load provider settings for {self._item.title} ({self._file}) "
                    f"playing from {mediaProvider2str(self._mediaProvider)}"
                ),
                xbmc.LOGWARNING
            )
            return

        # load external subtitles
        if providerSettings.getBool(SETTINGS_PROVIDER_PLAYBACK_ENABLE_EXTERNAL_SUBTITLES):
            self._addExternalSubtitles(plexServer)

    def _handleImportSettings(self):
        # load import settings
        importSettings = self._mediaImport.prepareSettings()
        if not importSettings:
            log(
                (
                    f"failed to load import settings for {self._item.title} ({self._file}) "
                    f"playing from {mediaProvider2str(self._mediaProvider)}"
                ),
                xbmc.LOGWARNING
            )
            return

        # try to get an intro marker
        self._getIntroMarker(importSettings)

        # try to get ad markers
        self._getAdMarkers(importSettings)

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

    def _getIntroMarker(self, importSettings: Settings):
        if not isinstance(self._item, Episode) or not self._item.hasIntroMarker:
            return

        # handle skipping intros
        self._skipIntroSetting = importSettings.getString(SETTINGS_IMPORT_PLAYBACK_SKIP_INTRO)
        if self._skipIntroSetting == SETTINGS_IMPORT_PLAYBACK_SKIP_NEVER:
            log(
                (
                    f"ignoring available intro markers for {self._item.title} ({self._file}) "
                    f"playing from {mediaProvider2str(self._mediaProvider)}"
                )
            )
            return

        # find all intro markers
        introMarkers = [marker for marker in self._item.markers if marker.type == 'intro']
        if len(introMarkers) != 1:
            log(
                (
                    f"bad number of intro markers for {self._item.title} ({self._file}) "
                    f"playing from {mediaProvider2str(self._mediaProvider)}"
                ),
                xbmc.LOGWARNING
            )
            return

        self._introMarker = introMarkers[0]
        log((
            f"found intro marker {self._introMarker} for {self._item.title} ({self._file}) "
            f"playing from {mediaProvider2str(self._mediaProvider)}"
        ))

    def _getAdMarkers(self, importSettings: Settings):
        if not isinstance(self._item, Episode) or not self._item.hasCommercialMarker:
            return

        # handle skipping ads
        self._skipAdsSetting = importSettings.getString(SETTINGS_IMPORT_PLAYBACK_SKIP_ADS)
        if self._skipAdsSetting == SETTINGS_IMPORT_PLAYBACK_SKIP_NEVER:
            log(
                (
                    f"ignoring available ad markers for {self._item.title} ({self._file}) "
                    f"playing from {mediaProvider2str(self._mediaProvider)}"
                )
            )
            return

        # find all ad markers
        self._adMarkers = [marker for marker in self._item.markers if marker.type == 'commercial']
        log((
            f"found {len(self._adMarkers)} ad markers for {self._item.title} ({self._file}) "
            f"playing from {mediaProvider2str(self._mediaProvider)}"
        ))

    def _processPlayback(self):
        playbackTime = self._getPlayingTime()
        self._processIntroMarker(playbackTime=playbackTime)
        self._processAdMarkers(playbackTime=playbackTime)

    def _processIntroMarker(self, playbackTime: float):
        # nothing to do if there are no intro markers
        if not self._introMarker:
            return

        markerStart = self._introMarker.start
        markerEnd = self._introMarker.end

        # nothing to do if the current playback time is outside of the intro marker
        if markerStart > playbackTime or markerEnd < playbackTime:
            # close the skip intro dialog if it is still open
            if self._skipDialog:
                self._skipDialog.close()
                self._skipDialog = None
            return

        skipIntro = False
        if self._skipIntroSetting == SETTINGS_IMPORT_PLAYBACK_SKIP_ALWAYS:
            skipIntro = True
        elif self._skipIntroSetting == SETTINGS_IMPORT_PLAYBACK_SKIP_ASK:
            if not self._skipDialog:
                log(
                    (
                        f"asking to skip intro starting at {markerStart}ms to {markerEnd}ms for "
                        f"{self._item.title} ({self._file})"
                    )
                )
                # create and open the skip intro dialog
                self._skipDialog = SkipDialog.Create(32031)
                self._skipDialog.show()

            # check if skipping the intro has been confirmed
            if self._skipDialog.skip():
                skipIntro = True

        if skipIntro:
            log(f"skipping intro starting at {markerStart}ms to {markerEnd}ms for {self._item.title} ({self._file})")
            self.seekTime(milliToSeconds(markerEnd))

    def _processAdMarkers(self, playbackTime: float):
        # nothing to do if there are no ad markers
        if not self._adMarkers:
            return False

        adMarker = [marker for marker in self._adMarkers if marker.start <= playbackTime and marker.end > playbackTime]

        # nothing to do if the current playback time is outside of all ad markers
        if not adMarker:
            # close the skip dialog if it is still open
            if self._skipDialog:
                self._skipDialog.close()
                self._skipDialog = None
            return False

        # get the actual ad marker
        adMarker = adMarker[0]
        markerStart = adMarker.start
        markerEnd = adMarker.end

        skipAd = False
        if self._skipAdsSetting == SETTINGS_IMPORT_PLAYBACK_SKIP_ALWAYS:
            skipAd = True
        elif self._skipAdsSetting == SETTINGS_IMPORT_PLAYBACK_SKIP_ASK:
            if not self._skipDialog:
                log(
                    (
                        f"asking to skip ad starting at {markerStart}ms to {markerEnd}ms for "
                        f"{self._item.title} ({self._file})"
                    )
                )
                # create and open the skip dialog
                self._skipDialog = SkipDialog.Create(32036)
                self._skipDialog.show()

            # check if skipping the ad has been confirmed
            if self._skipDialog.skip():
                skipAd = True

        if skipAd:
            log(f"skipping ad starting at {markerStart}ms to {markerEnd}ms for {self._item.title} ({self._file})")
            self.seekTime(milliToSeconds(markerEnd))

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

        if playbackTime:
            self._state['playbackTime'] = int(playbackTime)

        # Send update to PMS and update last report timestamp
        if self._state.get('playbackTime') and self._state.get('state'):
            self._state['lastreport'] = time.time()
            self._item.updateTimeline(
                self._state['playbackTime'],
                state=self._state['state'],
                duration=self._duration
            )

    def _getPlayingTime(self) -> float:
        """Gets current xbmc.Player time in miliseconds"""
        try:
            return toMilliseconds(self.getTime())
        except RuntimeError:
            return 0

    def _reset(self):
        """Resets player member variables to default"""
        # Player item
        self._file = None
        self._item = None
        self._itemId = None
        self._mediaProvider = None
        self._mediaImport = None
        self._skipDialog = None
        self._skipIntroSetting = SETTINGS_IMPORT_PLAYBACK_SKIP_NEVER
        self._skipAdsSetting = SETTINGS_IMPORT_PLAYBACK_SKIP_NEVER
        self._introMarker = None
        self._adMarkers = []
        self._duration = None
        # Player last known state
        self._state = {'playbackTime': 0, 'state': None, 'lastreport': 0}
        self._lastProcessing = 0
