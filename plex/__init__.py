#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#
"""
Package to facilitate interaction with Plex and Kodi for the addon.

Modules:
    api
    constants
    player
    provider_observer
    server
"""


def Initialize() -> None:
    """Initialize the package by setting some base variables in the plexapi"""
    import xbmc  # pylint: disable=import-error,import-outside-toplevel

    import plexapi  # pylint: disable=import-outside-toplevel

    plexapi.X_PLEX_PRODUCT = 'Kodi'
    plexapi.X_PLEX_VERSION = xbmc.getInfoLabel('System.BuildVersionShort')
    plexapi.X_PLEX_DEVICE_NAME = xbmc.getInfoLabel('System.FriendlyName')

    plexapi.BASE_HEADERS['X-Plex-Product'] = plexapi.X_PLEX_PRODUCT
    plexapi.BASE_HEADERS['X-Plex-Version'] = plexapi.X_PLEX_VERSION
    plexapi.BASE_HEADERS['X-Plex-Device-Name'] = plexapi.X_PLEX_DEVICE_NAME
