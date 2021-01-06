#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#
"""
Collection of utility functions and classes for logging, data conversion, etc.

Functions:
    log
    string2Unicode
    nomalizeString
    localise
    toMilliseconds
    mediaProvider2str
    mediaImport2str
"""

import unicodedata

from six import PY3

import xbmc  # pylint: disable=import-error
import xbmcaddon  # pylint: disable=import-error
import xbmcmediaimport  # pylint: disable=import-error

__addon__ = xbmcaddon.Addon()
__addonid__ = __addon__.getAddonInfo('id')


def log(message: str, level: int = xbmc.LOGINFO):
    """Log function to send logs into the Kodi log system

    :param message: Log message to send to Kodi
    :type message: str
    :param level: Kodi log level (LOGNONE, LOGDEBUG, *LOGINFO, LOGNOTICE, LOGWARNING, LOGERROR, LOGSEVERE, LOGFATAL)
    :type level: int, optional
    """
    if not PY3:
        try:
            message = message.encode('utf-8')
        except UnicodeDecodeError:
            message = message.decode('utf-8').encode('utf-8', 'ignore')

    xbmc.log(f"[{__addonid__}] {message}", level)


# fixes unicode problems
def string2Unicode(text: str, encoding: str = 'utf-8') -> str:
    """Helper function for encoding strings

    :param text: String of text to encode
    :type text: str
    :param encoding: The type of encoding to use, defaults to 'utf-8'
    :type encoding: str, optional
    :return: Encoded text
    :rtype: str
    """
    try:
        if PY3:
            text = str(text)
        else:
            text = unicode(text, encoding)  # noqa: F821
    except:
        pass

    return text


def normalizeString(text: str) -> bytes:
    """Helper function to normaize a string of text to ascii bytestring

    :param text:
    :type text: str
    :return: Normalized/encoded string of ascii text
    :rtype: bytes
    """
    try:
        text = unicodedata.normalize('NFKD', string2Unicode(text)).encode('ascii', 'ignore')
    except:
        pass

    return text


def localize(identifier: int, format_input: str = "") -> bytes:
    """Helper function to pull localized strings from language resources

    :param id: ID of the string to pull from the resource database
    :type id: int
    :param format_input: String to .format into the localized string before encoding
    :type format_input: str, optional
    :return: Localized and normalized byte string
    :rtype: bytes
    """
    local_string = __addon__.getLocalizedString(identifier)
    return normalizeString(local_string.format(format_input))


def toMilliseconds(seconds: float) -> int:
    """Helper function to convert seconds(float) to milliseconds(int)

    :param seconds: Time in seconds
    :type seconds: float
    :return: Time in milliseconds
    :rtype: int
    """
    return int(seconds) * 1000


def mediaProvider2str(mediaProvider: xbmcmediaimport.MediaProvider):
    """Helper function to convert a MediaProvider object into a string for logging

    :param mediaProvider: MediaProvider to convert into a string
    :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
    :return: String representing the MediaProvider for logs
    :rtype: str
    """
    if not mediaProvider:
        raise ValueError('invalid mediaProvider')

    return f"'{mediaProvider.getFriendlyName()}' ({mediaProvider.getIdentifier()})"


def mediaImport2str(mediaImport: xbmcmediaimport.MediaImport):
    """Helper function to convert a MediaImport object into a string for logging

    :param mediaImport: MediaImport to convert into a string
    :type mediaImport: :class:`xbmcmediaimport.MediaImport`
    :return: String representing the MediaImport for logs
    :rtype: str
    """
    if not mediaImport:
        raise ValueError('invalid mediaImport')

    return f"{mediaImport.getPath()} ({mediaImport.getMediaTypes()})"

def getIcon():
    iconPath = xbmc.translatePath(__addon__.getAddonInfo('icon'))
    try:
        iconPath = iconPath.decode('utf-8')
    except AttributeError:
        pass

    return iconPath
