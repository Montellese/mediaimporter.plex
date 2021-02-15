#!/usr/bin/python
# -*- coding: utf-8 -*-/*
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#
from __future__ import annotations  # Necessary for forward reference annotations (return of fromString method)
import time

from six import iteritems

import xbmc  # pylint: disable=import-error
import xbmcmediaimport  # pylint: disable=import-error

from plexapi.gdm import GDM

from lib.monitor import Monitor
from lib.settings import ProviderSettings
from lib.utils import getIcon, log, mediaProvider2str

import plex
from plex.server import Server


class PlexServer():
    """Class for storing and representing connection details and state of a Plex server"""
    def __init__(self):
        self.id = ''
        self.name = ''
        self.address = ''
        self.registered = False
        self.lastseen = 0.0

    def isExpired(self, timeoutS: float) -> bool:
        """Check if the PMS has been seen within the timeout period

        :param timeoutS: Timeout value in seconds
        :type timeoutS: float
        :return: Whether the PMS has been seen within the timeout period or not
        :rtype: bool
        """
        return self.registered and self.lastseen + timeoutS < time.time()

    @staticmethod
    def fromData(response: dict) -> PlexServer:
        """Construct and return a PlexServer object from discovery response data

        :param response: Response from a discovery message
        :type response: dict
        :return: Constructed PLexServer object
        :rtype: :class:`PlexServer`
        """
        AttributeData = 'data'
        AttributeFrom = 'from'
        AttributeResourceIdentifier = 'Resource-Identifier'
        AttributeName = 'Name'
        AttributePort = 'Port'

        # make sure the response is valid
        if not {AttributeData, AttributeFrom}.issubset(response.keys()):
            return None

        # make sure the data part of the response is valid
        data = response[AttributeData]
        if not {AttributeResourceIdentifier, AttributeName, AttributePort}.issubset(data.keys()):
            return None

        # make sure the from part of the response is valid
        from_data = response[AttributeFrom]
        if not isinstance(from_data, tuple) or len(from_data) != 2:
            return None

        identifier = data[AttributeResourceIdentifier]
        name = data[AttributeName]
        port = int(data[AttributePort])
        ip = from_data[0]

        if not identifier or not name or port <= 0 or port > 65535:
            return None

        server = PlexServer()
        server.id = identifier
        server.name = name
        server.address = f"http://{ip}:{port}"
        server.registered = False
        server.lastseen = time.time()

        return server


class DiscoveryService:
    """Class that handles discovery of Plex servers on the local network"""

    def __init__(self):
        self._monitor = Monitor()
        self._gdm = GDM()
        self._servers = {}

        self._start()

    def _discover(self):
        """Uses plexapi's GDM class to discover servers"""
        servers = self._gdm.find_by_content_type('plex/media-server')

        for server in servers:
            plexServer = PlexServer.fromData(server)
            if plexServer:
                self._addServer(plexServer)

    def _addServer(self, server: PlexServer):
        """Add a discovered PMS server as a MediaProvider to the Kodi mediaimport system

        :param server: The discovered PlexServer to add into the Kodi mediaimport system
        :type server: :class:`PlexServer`
        """
        registerServer = False

        # check if the server is already known
        if server.id not in self._servers:
            self._servers[server.id] = server
            registerServer = True
        else:
            # check if the server has already been registered or if some of its properties have changed
            if (
                    not self._servers[server.id].registered
                    or self._servers[server.id].name != server.name
                    or self._servers[server.id].address != server.address
            ):
                self._servers[server.id] = server
                registerServer = True
            else:
                # simply update the server's last seen property
                self._servers[server.id].lastseen = server.lastseen

        # if the server doesn't need to be registered there's nothing else to do
        if not registerServer:
            return

        providerId = Server.BuildProviderId(server.id)
        providerIconUrl = getIcon()

        provider = xbmcmediaimport.MediaProvider(
            providerId,
            server.name,
            providerIconUrl,
            plex.constants.SUPPORTED_MEDIA_TYPES
        )

        # store local authentication in settings
        providerSettings = provider.prepareSettings()
        if not providerSettings:
            return

        ProviderSettings.SetUrl(providerSettings, server.address)
        ProviderSettings.SetAuthenticationMethod(providerSettings, \
            plex.constants.SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL)
        providerSettings.save()

        if xbmcmediaimport.addAndActivateProvider(provider):
            self._servers[server.id].registered = True
            log(f"Plex Media Server {mediaProvider2str(provider)} successfully added and activated", xbmc.LOGINFO)
        else:
            self._servers[server.id].registered = False
            log(f"failed to add and/or activate Plex Media Server {mediaProvider2str(provider)}", xbmc.LOGINFO)

    def _expireServers(self):
        """Check registered Plex servers against timeout and expire any inactive ones"""
        for serverId, server in iteritems(self._servers):
            if not server.isExpired(10):
                continue

            server.registered = False
            xbmcmediaimport.deactivateProvider(serverId)
            log(f"Plex Media Server '{server.name}' ({server.id}) deactivated due to inactivity", xbmc.LOGINFO)

    def _start(self):
        """Start the discovery and registration process"""
        log('Looking for Plex Media Servers...')

        while not self._monitor.abortRequested():
            # try to discover Plex media servers
            self._discover()

            # expire Plex media servers that haven't responded for a while
            self._expireServers()

            if self._monitor.waitForAbort(1):
                break
