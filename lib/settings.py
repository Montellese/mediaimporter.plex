#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import hashlib
import json
from six import ensure_binary
from typing import List

from plex.constants import (
    SETTINGS_IMPORT_SYNC_SETTINGS_HASH,
    SETTINGS_IMPORT_LIBRARY_SECTIONS
)

import xbmcaddon


class SynchronizationSettings:
    """Class for interacting with the import settings hash for determining settings changes effect synchronization"""
    @staticmethod
    def GetHash(importSettings: xbmcaddon.Settings) -> str:
        """Get current settings hash

        :param importSettings: Kodi import settings object to pull hash from
        :type importSettings: :class:`xbmcaddmon.Settings`
        :return: Current settings hash pulled from Kodi
        :rtype: str
        """
        if not importSettings:
            raise ValueError('invalid importSettings')

        return importSettings.getString(SETTINGS_IMPORT_SYNC_SETTINGS_HASH)

    @staticmethod
    def SaveHash(importSettings: xbmcaddon.Settings, hashHex: str):
        """Save a settings hash string into the Kodi settings

        :param importSettings: Kodi settings object to store the hash into
        :type importSettings: :class:`xbmcaddmon.Settings`
        :param hashHex: Hex string to store in the Kodi settings
        :type hashHex: str
        """
        if not importSettings:
            raise ValueError('invalid importSettings')
        if not hashHex:
            raise ValueError('invalid hashHex')

        importSettings.setString(SETTINGS_IMPORT_SYNC_SETTINGS_HASH, hashHex)
        importSettings.save()

    @staticmethod
    def CalculateHash(importSettings: xbmcaddon.Settings, providerSettings: xbmcaddon.Settings, save: bool = True):
        """Generate the settings hash from the current settings in provided importSettings

        :param importSettings: Kodi settings object to pull the current import settings from
        :type importSettings: :class:`xbmcaddmon.Settings`
        :param providerSettings: Kodi settings object to pull the current provider settings from
        :type providerSettings: :class:`xbmcaddmon.Settings`
        :param save: Whether the generated hash should be stored into the settings object or not
        :type save: bool
        """
        if not importSettings:
            raise ValueError('invalid importSettings')

        # import specific settings
        librarySections = importSettings.getStringList(SETTINGS_IMPORT_LIBRARY_SECTIONS)

        hashObject = {
            # import specific settings
            SETTINGS_IMPORT_LIBRARY_SECTIONS: librarySections,
        }

        # serialize the object into JSON
        hashString = json.dumps(hashObject)

        # hash the JSON serialized object
        hash = hashlib.sha1(ensure_binary(hashString))
        hashHex = hash.hexdigest()

        if save:
            SynchronizationSettings.SaveHash(importSettings, hashHex)

        return hashHex

    @staticmethod
    def HaveChanged(importSettings: xbmcaddon.Settings, providerSettings: xbmcaddon.Settings, save: bool = True):
        """Check if the setting have changed by generating a new hash and comparing it to the stored one

        :param importSettings: Kodi settings object to pull the current import settings from
        :type importSettings: :class:`xbmcaddmon.Settings`
        :param providerSettings: Kodi settings object to pull the current provider settings from
        :type providerSettings: :class:`xbmcaddmon.Settings`
        :param save: Whether the new hash should be stored into the settings object if it has changed
        :type save: bool
        """
        if not importSettings:
            raise ValueError('invalid importSettings')

        oldHash = SynchronizationSettings.GetHash(importSettings)
        newHash = SynchronizationSettings.CalculateHash(importSettings, providerSettings, save=False)

        if oldHash == newHash:
            return False

        if save:
            SynchronizationSettings.SaveHash(importSettings, newHash)

        return True
    
    @staticmethod
    def ResetHash(importSettings: xbmcaddon.Settings, save: bool = True):
        """Reset the settings hash to empty to force a full sync on next run
        :param importSettings: Kodi settings object to store the empty settings hash into
        :type importSettings: :class:`xbmcaddmon.Settings`
        :param save: Whether the new hash should be stored into the settings object if it has changed
        :type save: bool
        """
        if not importSettings:
            raise ValueError('invalid importSettings')

        importSettings.setString(SETTINGS_IMPORT_SYNC_SETTINGS_HASH, '')
        if save:
            importSettings.save()