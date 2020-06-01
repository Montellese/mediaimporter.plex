#!/usr/bin/python
# -*- coding: utf-8 -*-/*
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#
from __future__ import annotations  # Necessary for forward reference annotations (return of fromString method)
import time
import socket
import struct

from six import iteritems

import xbmc  # pylint: disable=import-error
import xbmcmediaimport  # pylint: disable=import-error

from lib.monitor import Monitor
from lib.utils import log, mediaProvider2str

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
    def fromString(data: str, ip: str) -> PlexServer:
        """Construct and return a PlexServer object from discovery response data

        :param data: Response from a discovery message
        :type data: str
        :param ip: IP address the response was received from
        :type ip: str
        :return: Constructed PLexServer object
        :rtype: :class:`PlexServer`
        """
        Separator = b':'
        ServerPropertyResourceIdentifier = b'Resource-Identifier'
        ServerPropertyName = b'Name'
        ServerPropertyPort = b'Port'

        if not data:
            return None
        if not ip:
            return None

        identifier = None
        name = None
        port = 32400

        for line in data.splitlines():
            lineParts = [linePart.strip() for linePart in line.split(Separator)]
            if len(lineParts) > 2:
                lineParts = [lineParts[0], Separator.join(lineParts[1:])]
            if len(lineParts) != 2:
                continue

            serverProperty, serverPropertyValue = lineParts
            if serverProperty == ServerPropertyResourceIdentifier:
                identifier = serverPropertyValue.decode('utf-8')
            elif serverProperty == ServerPropertyName:
                name = serverPropertyValue.decode('utf-8')
            elif serverProperty == ServerPropertyPort:
                port = int(serverPropertyValue)

        if not identifier or not name or port <= 0 or port > 65535:
            return None

        server = PlexServer()
        server.id = identifier
        server.name = name
        server.address = f"http://{ip}:{port}"
        server.registered = False
        server.lastseen = time.time()

        if not server.id or not server.name or not server.address:
            return None

        return server


class DiscoveryService:
    """Class that handles discovery of Plex servers on the local network"""
    DiscoveryAddress = '239.0.0.250'
    DiscoveryPort = 32414
    DiscoveryMessage = b'M-SEARCH * HTTP/1.1\r\n'
    DiscoveryTimeoutS = 1.0
    DiscoveryResponsePort = 32412
    DiscoveryResponse = b'200 OK'

    def __init__(self):
        self._monitor = Monitor()
        self._sock = None
        self._servers = {}

        self._start()

    def _discover(self):
        """Sends discovery multicast message on the existing socket and waits for resposne, adding server if found"""
        # broadcast the discovery message
        self._sock.sendto(self.DiscoveryMessage, (self.DiscoveryAddress, self.DiscoveryPort))

        # try to receive an answer
        data = None
        address = None
        try:
            (data, address) = self._sock.recvfrom(1024)
        except socket.timeout:
            return

        if not address or not data or self.DiscoveryResponse not in data:
            return

        server = PlexServer.fromString(data, address[0])
        if server is not None:
            self._addServer(server)

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
        providerIconUrl = Server.BuildIconUrl(server.address)

        provider = xbmcmediaimport.MediaProvider(
            providerId,
            server.address,
            server.name,
            providerIconUrl,
            plex.constants.SUPPORTED_MEDIA_TYPES
        )

        # store local authentication in settings
        providerSettings = provider.prepareSettings()
        if not providerSettings:
            return

        providerSettings.setInt(
            plex.constants.SETTINGS_PROVIDER_AUTHENTICATION,
            plex.constants.SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL
        )
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

        # setup the UDP broadcast socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ttl = struct.pack('b', 1)
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        self._sock.settimeout(self.DiscoveryTimeoutS)

        while not self._monitor.abortRequested():
            # try to discover Plex media servers
            self._discover()

            # expire Plex media servers that haven't responded for a while
            self._expireServers()

            if self._monitor.waitForAbort(1):
                break

        self._sock.close()
