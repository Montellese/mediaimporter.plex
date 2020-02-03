#!/usr/bin/python
# -*- coding: utf-8 -*-/*
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import time
from six import iteritems
import socket
import struct

import xbmc
import xbmcaddon
import xbmcmediaimport

from lib.monitor import Monitor
from lib.utils import log, mediaProvider2str

import plex
from plex.server import Server

class PlexServer():
    def __init__(self):
        self.id = ''
        self.name = ''
        self.address = ''
        self.registered = False
        self.lastseen = None

    def isExpired(self, timeoutS):
        return self.registered and self.lastseen + timeoutS < time.time()

    @staticmethod
    def fromString(data, ip):
        Separator = b':'
        ServerPropertyResourceIdentifier = b'Resource-Identifier'
        ServerPropertyName = b'Name'
        ServerPropertyPort = b'Port'

        if not data:
            return None
        if not ip:
            return None

        id = None
        name = None
        port = 32400

        for line in data.splitlines():
            lineParts = [ linePart.strip() for linePart in line.split(Separator) ]
            if len(lineParts) > 2:
                lineParts = [ lineParts[0], Separator.join(lineParts[1:])]
            if len(lineParts) != 2:
                continue

            serverProperty, serverPropertyValue = lineParts
            if serverProperty == ServerPropertyResourceIdentifier:
                id = serverPropertyValue.decode('utf-8')
            elif serverProperty == ServerPropertyName:
                name = serverPropertyValue.decode('utf-8')
            elif serverProperty == ServerPropertyPort:
                port = int(serverPropertyValue)

        if not id or not name or port <= 0 or port > 65535:
            return None

        server = PlexServer()
        server.id = id
        server.name = name
        server.address = 'http://{}:{}'.format(ip, port)
        server.registered = False
        server.lastseen = time.time()

        if not server.id or not server.name or not server.address:
            return None

        return server

class DiscoveryService:
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
        # broadcast the discovery message
        self._sock.sendto(self.DiscoveryMessage, (self.DiscoveryAddress, self.DiscoveryPort))

        # try to receive an answer
        data = None
        address = None
        try:
            (data, address) = self._sock.recvfrom(1024)
        except socket.timeout:
            return # nothing to do

        if not address or not data or not self.DiscoveryResponse in data:
            return # nothing to do

        server = PlexServer.fromString(data, address[0])
        if not server is None:
            self._addServer(server)

    def _addServer(self, server):
        registerServer = False

        # check if the server is already known
        if not server.id in self._servers:
            self._servers[server.id] = server
            registerServer = True
        else:
            # check if the server has already been registered or if some of its properties have changed
            if not self._servers[server.id].registered or self._servers[server.id].name != server.name or self._servers[server.id].address != server.address:
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

        provider = xbmcmediaimport.MediaProvider(providerId, server.address, server.name, providerIconUrl, plex.constants.SUPPORTED_MEDIA_TYPES)

        # store local authentication in settings
        providerSettings = provider.prepareSettings()
        if not providerSettings:
            return None

        providerSettings.setInt(plex.constants.SETTINGS_PROVIDER_AUTHENTICATION, plex.constants.SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL_NOAUTH)
        providerSettings.save()

        if xbmcmediaimport.addAndActivateProvider(provider):
            self._servers[server.id].registered = True
            log('Plex Media Server {} successfully added and activated'.format(mediaProvider2str(provider)))
        else:
            self._servers[server.id].registered = False
            log('failed to add and/or activate Plex Media Server {}'.format(mediaProvider2str(provider)))

    def _expireServers(self):
        for serverId, server in iteritems(self._servers):
            if not server.isExpired(10):
                continue

            server.registered = False
            xbmcmediaimport.deactivateProvider(serverId)
            log('Plex Media Server "{}" ({}) deactivated due to inactivity'.format(server.name, server.id))

    def _start(self):
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
