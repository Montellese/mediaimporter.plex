#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import xbmcmediaimport

from lib.monitor import Monitor
from lib.utils import log, mediaImport2str, mediaProvider2str

from plex.player import Player
from plex.provider_observer import ProviderObserver

class PlexObserverService(xbmcmediaimport.Observer):
    """Class that handles observation of Plex servers for live updates"""
    def __init__(self):
        super(xbmcmediaimport.Observer, self).__init__()

        self._monitor = Monitor()
        self._player = Player()
        self._observers = {}

        self._run()

    def _run(self):
        """Begin observing configured Plex servers"""
        log('Observing Plex servers...')

        while not self._monitor.abortRequested():
            # process the player
            self._player.Process()

            # process all observers
            for observer in self._observers.values():
                observer.Process()

            if self._monitor.waitForAbort(1):
                break

        # stop all observers
        for observer in self._observers.values():
            observer.Stop()

    def _addObserver(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Register a new observer (Plex server) in the observation process

        :param mediaProvider: Plex Server MediaProvider object to observe
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        if not mediaProvider:
            raise ValueError('cannot add invalid media provider')

        self._player.AddProvider(mediaProvider)

        # check if we already know about the media provider
        mediaProviderId = mediaProvider.getIdentifier()
        if mediaProviderId in self._observers:
            return

        # create the observer
        self._observers[mediaProviderId] = ProviderObserver()

    def _removeObserver(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Remove a registered observer (Plex sever) from the observation process

        :param mediaProvider: Plex Server MediaProvider object to remove from observation
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        if not mediaProvider:
            raise ValueError('cannot remove invalid media provider')

        self._player.RemoveProvider(mediaProvider)

        mediaProviderId = mediaProvider.getIdentifier()
        if mediaProviderId not in self._observers:
            return

        del self._observers[mediaProviderId]

    def _startObserver(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Start observation on the provided MediaProvider (Plex server)

        :param mediaProvider: Plex Server MediaProvider object to observe
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        if not mediaProvider:
            raise ValueError('cannot start invalid media provider')

        # make sure the media provider has been added
        self._addObserver(mediaProvider)

        # start observing the media provider
        self._observers[mediaProvider.getIdentifier()].Start(mediaProvider)

    def _stopObserver(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Stp[ observation on the provided MediaProvider (Plex server)

        :param mediaProvider: Plex Server MediaProvider object to stop observation of
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        if not mediaProvider:
            raise ValueError('cannot stop invalid media provider')

        mediaProviderId = mediaProvider.getIdentifier()
        if mediaProviderId not in self._observers:
            return

        self._observers[mediaProviderId].Stop()

    def _addImport(self, mediaImport: xbmcmediaimport.MediaImport):
        """Add provided mediaImport task to the associated MediaProvider observer

        :param mediaImport: MediaImport task to add to provider
        :type mediaImport: :class:`xbmcmediaimport.MediaImport`
        """
        if not mediaImport:
            raise ValueError('cannot add invalid media import')

        mediaProvider = mediaImport.getProvider()
        if not mediaProvider:
            raise ValueError(f"cannot add media import {mediaImport2str(mediaImport)} with invalid media provider")

        mediaProviderId = mediaProvider.getIdentifier()
        if mediaProviderId not in self._observers:
            return

        self._observers[mediaProviderId].AddImport(mediaImport)

    def _removeImport(self, mediaImport: xbmcmediaimport.MediaImport):
        """Remove provided mediaImport task to the associated MediaProvider observer

        :param mediaImport: MediaImport task to remove from provider
        :type mediaImport: :class:`xbmcmediaimport.MediaImport`
        """
        if not mediaImport:
            raise ValueError('cannot remove invalid media import')

        mediaProvider = mediaImport.getProvider()
        if not mediaProvider:
            raise ValueError(f"cannot remove media import {mediaImport2str(mediaImport)} with invalid media provider")

        mediaProviderId = mediaProvider.getIdentifier()
        if mediaProviderId not in self._observers:
            return

        self._observers[mediaProviderId].RemoveImport(mediaImport)

    def onProviderAdded(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Event handler: triggered when a new provider is added to the system, register it as an observer

        :param mediaProvider: MediaProvider that was added to the system
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        self._addObserver(mediaProvider)

    def onProviderUpdated(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Event handler: triggered when a provider is updated in the system, make sure it is being observed

        :param mediaProvider: MediaProvider that was added to the system
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        self._addObserver(mediaProvider)

        # make sure the media provider is being observed
        if mediaProvider.isActive():
            self._startObserver(mediaProvider)
        else:
            self._stopObserver(mediaProvider)

    def onProviderRemoved(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Event handler: triggered when a provider is removed from the system, remove from observation

        :param mediaProvider: MediaProvider that was removed from the system
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        self._removeObserver(mediaProvider)

    def onProviderActivated(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Event handler: triggered when a provider is actived in the system, start observation

        :param mediaProvider: MediaProvider that was actived in the system
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        self._startObserver(mediaProvider)

    def onProviderDeactivated(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Event handler: triggered when a provider is deactived in the system, remove from observation

        :param mediaProvider: MediaProvider that was deactived in the system
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        self._stopObserver(mediaProvider)

    def onImportAdded(self, mediaImport: xbmcmediaimport.MediaImport):
        """Event handler: triggered when a new import task is added to the system, add to media provider

        :param mediaImport: MediaImport task added to the system
        :type mediaImport: :class:`xbmcmediaimport.MediaImport`
        """
        self._addImport(mediaImport)

    def onImportUpdated(self, mediaImport: xbmcmediaimport.MediaImport):
        """Event handler: triggered when a new import task is updated in the system, update in media provider

        :param mediaImport: MediaImport task updated in the system
        :type mediaImport: :class:`xbmcmediaimport.MediaImport`
        """
        self._addImport(mediaImport)

    def onImportRemoved(self, mediaImport: xbmcmediaimport.MediaImport):
        """Event handler: triggered when a new import task is removed from the system, remove from media provider

        :param mediaImport: MediaImport task removed from the system
        :type mediaImport: :class:`xbmcmediaimport.MediaImport`
        """
        self._removeImport(mediaImport)
