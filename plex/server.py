#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import plexapi.exceptions
from plexapi.server import PlexServer

from lib.utils import Url
from plex.constants import \
    PLEX_PROTOCOL, \
    SETTINGS_PROVIDER_AUTHENTICATION, SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL_NOAUTH, \
    SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL_TOKEN, SETTINGS_PROVIDER_TOKEN

class Server:
    def __init__(self, provider):
        if not provider:
            raise ValueError('Invalid provider')

        self._provider = provider
        self._id = self._provider.getIdentifier()
        self._url = self._provider.getBasePath()

        settings = self._provider.getSettings()
        if not settings:
            raise ValueError('Invalid provider without settings')

        self._localNoAuth = settings.getInt(SETTINGS_PROVIDER_AUTHENTICATION) == SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL_NOAUTH
        self._token = None
        if not self._localNoAuth:
            self._token =  settings.getString(SETTINGS_PROVIDER_TOKEN)
        self._plex = None

    def Authenticate(self):
        if not self._plex:
            try:
                self._plex = PlexServer(baseurl=self._url, token=self._token)

            except plexapi.exceptions.BadRequest as err:
                settings = self._provider.getSettings()
                if '(401) unauthorized' in str(err) and \
                    settings.getInt(SETTINGS_PROVIDER_AUTHENTICATION) == SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL_NOAUTH:
                        # provider is using local_noauth but server returned unauthorized
                        # change provider auth type to local_token so the user can fill the token value in the settings dialog
                        settings.setInt(SETTINGS_PROVIDER_AUTHENTICATION, SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL_TOKEN)
                return False
            except:
                return False

        return self._plex is not None

    def Id(self):
        return self._id

    def Url(self):
        return self._url

    def AccessToken(self):
        return self._token

    def PlexServer(self):
        self.Authenticate()
        return self._plex

    @staticmethod
    def BuildProviderId(serverId):
        if not serverId:
            raise ValueError('Invalid serverId')

        return '{}://{}/'.format(PLEX_PROTOCOL, serverId)

    @staticmethod
    def BuildIconUrl(baseUrl):
        if not baseUrl:
            raise ValueError('Invalid baseUrl')

        # TODO(Montellese)
        return ""
