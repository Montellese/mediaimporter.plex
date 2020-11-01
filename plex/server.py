#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from plexapi.server import PlexServer

from lib.settings import ProviderSettings

from plex.constants import (
    PLEX_PROTOCOL,
    SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL
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

        settings = provider.getSettings()
        if not settings:
            raise ValueError('Invalid provider without settings')

        self._url = ProviderSettings.GetUrl(settings)

        self._localOnly = bool(
            ProviderSettings.GetAuthenticationMethod(settings) == SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL
        )
        self._token = ""
        if not self._localOnly:
            self._token = ProviderSettings.GetAccessToken(settings)
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
