#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import xbmc
from xbmcgui import ListItem
import xbmcmediaimport

from plexapi import video

from plex.constants import *

from lib.utils import log

PLEX_LIBRARY_TYPE_MOVIE = 'movie'
PLEX_LIBRARY_TYPE_TVSHOW = 'show'
PLEX_LIBRARY_TYPE_SEASON = 'season'
PLEX_LIBRARY_TYPE_EPISODE = 'episode'

# mapping of Kodi and Plex media types
PLEX_MEDIA_TYPES = [
    { 'kodi': xbmcmediaimport.MediaTypeMovie, 'plex': PLEX_LIBRARY_TYPE_MOVIE, 'libtype': PLEX_LIBRARY_TYPE_MOVIE, 'label': 32002 },
    { 'kodi': xbmcmediaimport.MediaTypeTvShow, 'plex': PLEX_LIBRARY_TYPE_TVSHOW, 'libtype': PLEX_LIBRARY_TYPE_TVSHOW, 'label': 32003 },
    { 'kodi': xbmcmediaimport.MediaTypeSeason, 'plex': PLEX_LIBRARY_TYPE_TVSHOW, 'libtype': PLEX_LIBRARY_TYPE_SEASON, 'label': 32004 },
    { 'kodi': xbmcmediaimport.MediaTypeEpisode, 'plex': PLEX_LIBRARY_TYPE_TVSHOW, 'libtype': PLEX_LIBRARY_TYPE_EPISODE, 'label': 32005 },
    { 'kodi': xbmcmediaimport.MediaTypeMusicVideo, 'plex': PLEX_LIBRARY_TYPE_MOVIE, 'libtype': PLEX_LIBRARY_TYPE_MOVIE, 'label': 32006 }
]

class Api:
    @staticmethod
    def compareMediaProviders(lhs, rhs):
        if not lhs or not rhs:
            return False

        if lhs.getIdentifier() != rhs.getIdentifier():
            return False

        if lhs.getBasePath() != rhs.getBasePath():
            return False

        if lhs.getFriendlyName() != rhs.getFriendlyName():
            return False

        lhsSettings = lhs.prepareSettings()
        if not lhsSettings:
            return False

        rhsSettings = rhs.prepareSettings()
        if not rhsSettings:
            return False

        lhsSettingsAuthentication = lhsSettings.getInt(SETTINGS_PROVIDER_AUTHENTICATION)
        if lhsSettingsAuthentication != rhsSettings.getInt(SETTINGS_PROVIDER_AUTHENTICATION):
            return False

        if lhsSettingsAuthentication == SETTINGS_PROVIDER_AUTHENTICATION_OPTION_MYPLEX:
            if lhsSettings.getString(SETTINGS_PROVIDER_USERNAME) != rhsSettings.getString(SETTINGS_PROVIDER_USERNAME):
                return False

            if lhsSettings.getString(SETTINGS_PROVIDER_TOKEN) != rhsSettings.getString(SETTINGS_PROVIDER_TOKEN):
                return False

        return True

    @staticmethod
    def getPlexMediaType(mediaType):
        if not mediaType:
            raise ValueError('invalid mediaType')

        mappedMediaType = [ x for x in PLEX_MEDIA_TYPES if x['kodi'] == mediaType ]
        if not mappedMediaType:
            return None

        return mappedMediaType[0]

    @staticmethod
    def getKodiMediaTypes(plexMediaType):
        if not plexMediaType:
            raise ValueError('invalid plexMediaType')

        mappedMediaTypes = [ x for x in PLEX_MEDIA_TYPES if x['plex'] == plexMediaType ]
        if not mappedMediaTypes:
            return None

        return mappedMediaTypes

    @staticmethod
    def getKodiMediaTypesFromPlexLibraryTpe(plexLibraryType):
        if not plexLibraryType:
            raise ValueError('invalid plexLibraryType')

        mappedMediaTypes = [ x for x in PLEX_MEDIA_TYPES if x['libtype'] == plexLibraryType ]
        if not mappedMediaTypes:
            return None

        return mappedMediaTypes

    @staticmethod
    def validatePlexLibraryItemType(plexItem, libraryType):
        if not plexItem:
            raise ValueError('invalid plexItem')
        if not libraryType:
            raise ValueError('invalid libraryType')

        if not isinstance(plexItem, video.Video):
            return False

        if not plexItem.type == libraryType:
            return False

        plexMediaClass = Api.getPlexMediaClassFromLibraryType(libraryType)
        if not plexMediaClass:
            return False

        return isinstance(plexItem, plexMediaClass)

    @staticmethod
    def MillisecondsToSeconds(milliseconds):
        if not milliseconds:
            return 0.0

        return milliseconds / 1000

    @staticmethod
    def convertDateTimeToDbDate(dateTime):
        if not dateTime:
            return ''

        try:
            return dateTime.strftime('%Y-%m-%d')
        except ValueError:
            return ''

    @staticmethod
    def convertDateTimeToDbDateTime(dateTime):
        if not dateTime:
            return ''

        try:
            return dateTime.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            return ''

    @staticmethod
    def ListFromString(string):
        if not string:
            return []

        return [ stringPart.strip() for stringPart in string.split(';') ]

    @staticmethod
    def ListFromMediaTags(mediaTags):
        if not mediaTags:
            return []

        return [ mediaTag.tag.strip() for mediaTag in mediaTags ]

    @staticmethod
    def getItemIdFromListItem(listItem):
        return int(listItem.getUniqueID(PLEX_PROTOCOL))

    @staticmethod
    def getItemIdFromPlexKey(plexItemKey):
        parts = plexItemKey.split('/')
        if not parts:
            return None

        return int(parts[-1])

    @staticmethod
    def getPlexMediaClassFromMediaType(mediaType):
        mappedMediaType = Api.getPlexMediaType(mediaType)
        if not mappedMediaType:
            return None

        return Api.getPlexMediaClassFromLibraryType(mappedMediaType['libtype'])

    @staticmethod
    def getPlexMediaClassFromLibraryType(libraryType):
        if libraryType == PLEX_LIBRARY_TYPE_MOVIE:
            return video.Movie
        if libraryType == PLEX_LIBRARY_TYPE_TVSHOW:
            return video.Show
        if libraryType == PLEX_LIBRARY_TYPE_SEASON:
            return video.Season
        if libraryType == PLEX_LIBRARY_TYPE_EPISODE:
            return video.Episode

        return None

    @staticmethod
    def getPlexItemDetails(plexServer, plexItemId, plexItemClass=None):
        if not plexServer:
            raise ValueError('invalid plexServer')
        if not plexItemId:
            raise ValueError('invalid plexItemId')

        plexLibrary = plexServer.library
        if not plexLibrary:
            raise ValueError('plexServer does not contain a library')

        return plexLibrary.fetchItem(plexItemId, cls=plexItemClass)

    @staticmethod
    def getPlexItemAsListItem(plexServer, plexItemId, plexItemClass=None):
        if not plexServer:
            raise ValueError('invalid plexServer')
        if not plexItemId:
            raise ValueError('invalid plexItemId')

        plexItem = Api.getPlexItemDetails(plexServer, plexItemId, plexItemClass)
        if not plexItem:
            return None

        return Api.toFileItem(plexItem)

    @staticmethod
    def toFileItem(plexItem, mediaType=None, plexLibType=None):
        # determine the matching Plex library type if possible
        checkMediaType = mediaType is not None
        if checkMediaType and not plexLibType:
            mappedMediaType = Api.getPlexMediaType(mediaType)
            if not mappedMediaType:
                log('cannot import unsupported media type "{}"'.format(mediaType), xbmc.LOGERROR)
                return None

            plexLibType = mappedMediaType['libtype']

        # make sure the item matches the media type
        if plexLibType is not None and not Api.validatePlexLibraryItemType(plexItem, plexLibType):
            log('cannot import {} item from invalid Plex library item: {}'.format(mediaType, plexItem), xbmc.LOGERROR)
            return None

        # determine the Kodi media type based on the Plex library type
        if not checkMediaType:
            plexLibType = plexItem.type
            mappedMediaTypes = Api.getKodiMediaTypesFromPlexLibraryTpe(plexLibType)
            if not mappedMediaTypes:
                log('cannot import unsupported Plex library type "{}"'.format(plexLibType), xbmc.LOGERROR)
                return None

            if len(mappedMediaTypes) > 1:
                log('{} supported media type for Plex library type "{}"'.format(len(mappedMediaTypes), plexLibType), xbmc.LOGDEBUG)

            mediaType = mappedMediaTypes[0]['kodi']

        itemId = plexItem.ratingKey
        if not itemId:
            log('cannot import {} item without identifier'.format(mediaType), xbmc.LOGERROR)
            return None

        item = ListItem(label=plexItem.title)

        # fill video details
        Api.fillVideoInfos(itemId, plexItem, mediaType, item)

        if not item.getPath():
            log('failed to retrieve a path for {} item "{}"'.format(mediaType, item.getLabel()), xbmc.LOGWARNING)
            return None

        return item

    @staticmethod
    def fillVideoInfos(itemId, plexItem, mediaType, item):
        info = {
            'mediatype': mediaType,
            'path': '',
            'filenameandpath': '',
            'title': item.getLabel() or '',
            'sorttitle': plexItem.titleSort or '',
            'originaltitle': '',
            'plot': plexItem.summary or '',
            'dateadded': Api.convertDateTimeToDbDateTime(plexItem.addedAt),
            'year': 0,
            'set': '',
            'rating': 0.0,
            'userrating': 0.0,
            'mpaa': '',
            'duration': 0,
            'playcount': plexItem.viewCount,
            'lastplayed': Api.convertDateTimeToDbDateTime(plexItem.lastViewedAt),
            'director': [],
            'writer': [],
            'genre': [],
            'country': []
        }

        date = None
        isFolder = False

        resumePoint = {
            'totaltime': 0,
            'resumetime': 0
        }

        artwork = {}
        collections = []
        media = []
        locations = []
        roles = []

        if isinstance(plexItem, video.Movie):
            info.update({
                'mpaa': plexItem.contentRating or '',
                'duration': Api.MillisecondsToSeconds(plexItem.duration),
                'originaltitle': plexItem.originalTitle or '',
                'premiered': Api.convertDateTimeToDbDate(plexItem.originallyAvailableAt),
                'rating': plexItem.rating or 0.0,
                'studio': Api.ListFromString(plexItem.studio),
                'tagline': plexItem.tagline or '',
                'userrating': plexItem.userRating or 0.0,
                'year': plexItem.year or 0,
                'country': Api.ListFromMediaTags(plexItem.countries),
                'director': Api.ListFromMediaTags(plexItem.directors),
                'genre': Api.ListFromMediaTags(plexItem.genres),
                'writer': Api.ListFromMediaTags(plexItem.writers),
            })

            date = info['premiered']
            resumePoint['resumetime'] = Api.MillisecondsToSeconds(plexItem.viewOffset)
            collections = plexItem.collections
            media = plexItem.media
            roles = plexItem.roles
        elif isinstance(plexItem, video.Show):
            info.update({
                'mpaa': plexItem.contentRating or '',
                'duration': Api.MillisecondsToSeconds(plexItem.duration),
                'premiered': Api.convertDateTimeToDbDate(plexItem.originallyAvailableAt),
                'rating': plexItem.rating or 0.0,
                'studio': Api.ListFromString(plexItem.studio),
                'year': plexItem.year or 0,
                'genre': Api.ListFromMediaTags(plexItem.genres),
            })

            date = info['premiered']
            isFolder = True
            locations = plexItem.locations
            collections = plexItem.collections
            roles = plexItem.roles

            banner = plexItem.banner
            if banner:
                artwork['banner'] = plexItem.url(banner)
        elif isinstance(plexItem, video.Season):
            info.update({
                'tvshowtitle': plexItem.parentTitle or '',
                'season': plexItem.index,
            })
            isFolder = True
        elif isinstance(plexItem, video.Episode):
            info.update({
                'tvshowtitle': plexItem.grandparentTitle or '',
                'season': plexItem.parentIndex,
                'episode': plexItem.index,
                'mpaa': plexItem.contentRating or '',
                'duration': Api.MillisecondsToSeconds(plexItem.duration),
                'aired': Api.convertDateTimeToDbDate(plexItem.originallyAvailableAt),
                'rating': plexItem.rating or 0.0,
                'year': plexItem.year or 0,
                'director': Api.ListFromMediaTags(plexItem.directors),
                'writer': Api.ListFromMediaTags(plexItem.writers),
            })

            date = info['aired']
            resumePoint['resumetime'] = Api.MillisecondsToSeconds(plexItem.viewOffset)
            media = plexItem.media

        # handle collections / sets
        collections = Api.ListFromMediaTags(collections)
        if collections:
            # Kodi can only store one set per media item
            info['set'] = collections[0]

        # set the item's datetime if available
        if date:
            item.setDateTime(date)

        # specify whether the item is a folder or not
        item.setIsFolder(isFolder)

        # add the item's ID as a unique ID belonging to Plex
        item.getVideoInfoTag().setUniqueIDs({
            PLEX_PROTOCOL: itemId
        }, PLEX_PROTOCOL)

        # handle actors / cast
        cast = []
        for index, role in enumerate(roles):
            cast.append({
                'name': role.tag.strip(),
                'role': role.role.strip(),
                'order': index
            })
        if cast:
            item.setCast(cast)

        # handle resume point
        if resumePoint['resumetime'] > 0 and info['duration'] > 0:
            resumePoint['totaltime'] = info['duration']
            item.setProperties(resumePoint)

        # handle stream details
        mediaPart = None
        for mediaStream in media:
            for part in mediaStream.parts:
                # pick the first MediaPart with a valid file and stream URL
                if mediaPart is None and part.file is not None and part.key is not None:
                    mediaPart = part

                for videoStream in part.videoStreams():
                    item.addStreamInfo('video', {
                        'codec': videoStream.codec,
                        'language': videoStream.language,
                        'width': videoStream.width,
                        'height': videoStream.height,
                        'duration': info['duration']
                    })

                for audioStream in part.audioStreams():
                    item.addStreamInfo('audio', {
                        'codec': audioStream.codec,
                        'language': audioStream.language,
                        'channels': audioStream.channels
                     })

                for subtitleStream in part.subtitleStreams():
                    item.addStreamInfo('subtitle', {
                        'language': subtitleStream.language
                     })

        if mediaPart:
            # extract the absolute / actual path and the stream URL from the selected MediaPart
            info['path'] = mediaPart.file
            item.setPath(plexItem.url(mediaPart.key))
        elif isFolder:
            # for folders use locations for the path
            if locations:
                info['path'] = locations[0]
            item.setPath(plexItem.url(plexItem.key))
        info['filenameandpath'] = item.getPath()

        # set all the video infos
        item.setInfo('video', info)

        # handle artwork
        poster = plexItem.thumbUrl
        if poster:
            artwork['poster'] = poster
        fanart = plexItem.artUrl
        if fanart:
            artwork['fanart'] = fanart
        if artwork:
            item.setArt(artwork)
