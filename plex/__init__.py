#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

def Initialize():
    import xbmc

    import plexapi

    plexapi.X_PLEX_PRODUCT = 'Kodi'
    plexapi.X_PLEX_VERSION = xbmc.getInfoLabel('System.BuildVersionShort')
    plexapi.X_PLEX_DEVICE_NAME = xbmc.getInfoLabel('System.FriendlyName')

    plexapi.BASE_HEADERS['X-Plex-Product'] = plexapi.X_PLEX_PRODUCT
    plexapi.BASE_HEADERS['X-Plex-Version'] = plexapi.X_PLEX_VERSION
    plexapi.BASE_HEADERS['X-Plex-Device-Name'] = plexapi.X_PLEX_DEVICE_NAME
