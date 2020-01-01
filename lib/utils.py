#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import sys
from six.moves.urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import xbmc
import xbmcaddon

__addon__ = xbmcaddon.Addon()
__addonid__ = __addon__.getAddonInfo('id')

PY3 = sys.version_info.major >= 3

def log(message, level=xbmc.LOGINFO):
    if not PY3:
        try:
            message = message.encode('utf-8')
        except UnicodeDecodeError:
            message = message.decode('utf-8').encode('utf-8', 'ignore')
    xbmc.log('[{}] {}'.format(__addonid__, message), level)

# fixes unicode problems
def string2Unicode(text, encoding='utf-8'):
    try:
        if PY3:
            text = str(text)
        else:
            text = unicode(text, encoding)
    except:
        pass

    return text

def normalizeString(text):
    try:
        text = unicodedata.normalize('NFKD', string2Unicode(text)).encode('ascii', 'ignore')
    except:
        pass

    return text

def localise(id):
    return normalizeString(__addon__.getLocalizedString(id))

def mediaProvider2str(mediaProvider):
    if not mediaProvider:
        raise ValueError('invalid mediaProvider')

    return '"{}" ({})'.format(mediaProvider.getFriendlyName(), mediaProvider.getIdentifier())

def mediaImport2str(mediaImport):
    if not mediaImport:
        raise ValueError('invalid mediaImport')

    return '{} ({})'.format(mediaImport.getPath(), mediaImport.getMediaTypes())

class Url:
    @staticmethod
    def append(url, *args):
        if not url:
            return ''

        # remove a potentially trailing slash
        if url.endswith('/'):
            url = url[:-1]

        for arg in args:
            if not arg.startswith('/'):
                url += '/'

            url += arg

        return url

    @staticmethod
    def addOptions(url, options):
        if not url:
            return ''

        urlParts = list(urlparse(url))
        urlQuery = dict(parse_qsl(urlParts[4]))
        urlQuery.update(options)
        urlParts[4] = urlencode(urlQuery)
        return urlunparse(urlParts)
