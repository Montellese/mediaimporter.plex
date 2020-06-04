#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from plexapi.server import PlexServer

from plex.constants import (
    PLEX_PROTOCOL,
    SETTINGS_PROVIDER_AUTHENTICATION,
    SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL,
    SETTINGS_PROVIDER_TOKEN
)

import xbmcmediaimport  # pylint: disable=import-error


class Server:
    """Class to represent a Plex Media Server with helper methods for interacting with the plexapi

    :param provider: MediaProver from Kodi to implement
    :type provider: :class:`xbmcmediaimport.MediaProvider`
    """
    def __init__(self, provider: xbmcmediaimport.MediaProvider):
        if not provider:
            raise ValueError('Invalid provider')

        self._id = provider.getIdentifier()
        self._url = provider.getBasePath()

        settings = provider.getSettings()
        if not settings:
            raise ValueError('Invalid provider without settings')

        self._localOnly = bool(
            settings.getInt(SETTINGS_PROVIDER_AUTHENTICATION) == SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL
        )
        self._token = ""
        if not self._localOnly:
            self._token = settings.getString(SETTINGS_PROVIDER_TOKEN)
        self._plex = None

    def Authenticate(self):
        """Create an authenticated session with the Plex server"""
        if not self._plex:
            try:
                self._plex = PlexServer(baseurl=self._url, token=self._token)
            except:
                return False

        return self._plex is not None

    def Id(self) -> int:
        """Get the Id of the plex server"""
        return self._id

    def Url(self) -> str:
        """Get the Url of the plex server"""
        return self._url

    def AccessToken(self) -> str:
        """Get the AccessToken for the plex server"""
        return self._token

    def PlexServer(self) -> PlexServer:
        """Get an authenticated plex session object from plexapi

        :return: Authenticated plex session through plexapi PlexServer object
        :rtype: :class:`PlexServer`
        """
        self.Authenticate()
        return self._plex

    @staticmethod
    def BuildProviderId(serverId: int):
        """Format a ProviderId string using the provided serverId

        :param serverId: ID of the server to format into a PrivderId
        :type serverId: int
        :return: ProviderId formatted string
        :rtype: str
        """
        if not serverId:
            raise ValueError('Invalid serverId')

        return f"{PLEX_PROTOCOL}://{serverId}/"

    @staticmethod
    def BuildIconUrl(baseUrl: str) -> str:
        """Format the URL for icons from the provided baseUrl, NOT IMPLEMENTED

        :param baseUrl: URL to use as the base for the icon url
        :type baseUrl: str
        :return: Formatted Icon URL string
        :rtype: str
        """
        if not baseUrl:
            raise ValueError('Invalid baseUrl')

        # TODO(Montellese)
        return ""
