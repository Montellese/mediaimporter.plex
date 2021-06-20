#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#
import datetime
import json
from six.moves.urllib.parse import urlparse
from typing import List

import xbmc  # pylint: disable=import-error
from xbmcgui import ListItem  # pylint: disable=import-error
import xbmcvfs  # pylint: disable=import-error
import xbmcmediaimport  # pylint: disable=import-error

import plexapi
from plexapi import collection, media, server, video

from plex.constants import *

from lib.settings import ProviderSettings
from lib.utils import log

PLEX_LIBRARY_TYPE_MOVIE = 'movie'
PLEX_LIBRARY_TYPE_TVSHOW = 'show'
PLEX_LIBRARY_TYPE_SEASON = 'season'
PLEX_LIBRARY_TYPE_EPISODE = 'episode'
PLEX_LIBRARY_TYPE_COLLECTION = 'collection'

# mapping of Kodi and Plex media types
PLEX_MEDIA_TYPES = [
    {
        'kodi': xbmcmediaimport.MediaTypeMovie,
        'plex': PLEX_LIBRARY_TYPE_MOVIE,
        'libtype': PLEX_LIBRARY_TYPE_MOVIE,
        'label': 32002
    },
    {
        'kodi': xbmcmediaimport.MediaTypeVideoCollection,
        'plex': PLEX_LIBRARY_TYPE_COLLECTION,
        'libtype': PLEX_LIBRARY_TYPE_COLLECTION,
        'label': 32007
    },
    {
        'kodi': xbmcmediaimport.MediaTypeTvShow,
        'plex': PLEX_LIBRARY_TYPE_TVSHOW,
        'libtype': PLEX_LIBRARY_TYPE_TVSHOW,
        'label': 32003
    },
    {
        'kodi': xbmcmediaimport.MediaTypeSeason,
        'plex': PLEX_LIBRARY_TYPE_TVSHOW,
        'libtype': PLEX_LIBRARY_TYPE_SEASON,
        'label': 32004
    },
    {
        'kodi': xbmcmediaimport.MediaTypeEpisode,
        'plex': PLEX_LIBRARY_TYPE_TVSHOW,
        'libtype': PLEX_LIBRARY_TYPE_EPISODE,
        'label': 32005
    },
    {
        'kodi': xbmcmediaimport.MediaTypeMusicVideo,
        'plex': PLEX_LIBRARY_TYPE_MOVIE,
        'libtype': PLEX_LIBRARY_TYPE_MOVIE,
        'label': 32006
    }
]


class Api:
    """Static class with helper methods for working with the Plex and Kodi APIs"""
    @staticmethod
    def compareMediaProviders(lhs: object, rhs: object) -> bool:
        """Check if the provided mediaProvier objects are identical or not.

        :param lhs: First media provider to compare
        :type lhs: object
        :param rhs: Second media provider to compare
        :type rhs: object
        :return: Whether the media providers are identical or not
        :rtype: bool
        """
        if not lhs or not rhs:
            return False

        if lhs.getIdentifier() != rhs.getIdentifier():
            return False

        if lhs.getFriendlyName() != rhs.getFriendlyName():
            return False

        lhsSettings = lhs.prepareSettings()
        if not lhsSettings:
            return False

        rhsSettings = rhs.prepareSettings()
        if not rhsSettings:
            return False

        lhsSettingsAuthentication = ProviderSettings.GetAuthenticationMethod(lhsSettings)
        if lhsSettingsAuthentication != ProviderSettings.GetAuthenticationMethod(rhsSettings):
            return False

        if lhsSettingsAuthentication == SETTINGS_PROVIDER_AUTHENTICATION_OPTION_MYPLEX:
            if ProviderSettings.GetUsername(lhsSettings) != ProviderSettings.GetUsername(rhsSettings):
                return False

            if ProviderSettings.GetAccessToken(lhsSettings) != ProviderSettings.GetAccessToken(rhsSettings):
                return False

        return True

    @staticmethod
    def getPlexMediaType(mediaType: str) -> dict:
        """Get the Plex media type matching the provided Kodi media type

        :param mediaType: Kodi media type obejct
        :type mediaType: str
        :return: Mapping entry, dict with kodi, plex, libtype, and label keys
        :rtype: dict
        """
        if not mediaType:
            raise ValueError('invalid mediaType')

        mappedMediaType = [x for x in PLEX_MEDIA_TYPES if x['kodi'] == mediaType]
        if not mappedMediaType:
            return {}

        return mappedMediaType[0]

    @staticmethod
    def getKodiMediaTypes(plexMediaType: str) -> List[dict]:
        """Get the Kodi media types matching the provided Plex media type

        :param plexMediaType: Plex media type (movie, show, collection)
        :type plexMediaType: str
        :return: List of matching media type mapping dict
        :rtype: list
        """
        if not plexMediaType:
            raise ValueError('invalid plexMediaType')

        mappedMediaTypes = [x for x in PLEX_MEDIA_TYPES if x['plex'] == plexMediaType]
        if not mappedMediaTypes:
            return []

        return mappedMediaTypes

    @staticmethod
    def getKodiMediaTypesFromPlexLibraryType(plexLibraryType: str) -> List[dict]:
        """Get the Kodi media types matching the provided library type

        :param plexLibraryType: Type of plex library (movie, show, season, episode, collection)
        :type plexLibraryType: str
        :return: List of matching media type mapping dict
        :rtype: list
        """
        if not plexLibraryType:
            raise ValueError('invalid plexLibraryType')

        mappedMediaTypes = [x for x in PLEX_MEDIA_TYPES if x['libtype'] == plexLibraryType]
        if not mappedMediaTypes:
            return []

        return mappedMediaTypes

    @staticmethod
    def validatePlexLibraryItemType(plexItem: video.Video, libraryType: str) -> bool:
        """Perform validation on the plexItem, confirming it belongs in the provided library type

        :param plexItem: Plex item to validate
        :type plexItem: class:`video.Video`
        :param libraryType: Type of plex library (movie, show, season, episode, collection)
        :type libraryType: str
        :return: Status of validation, whether the plex item belongs in the library or not
        :rtype: bool
        """
        # ATTENTION: don't change this to "if not plexItem" because folders (e.g. collections) with no
        #            content are considered faulty
        if not plexItem:
            raise ValueError('invalid plexItem')
        if not libraryType:
            raise ValueError('invalid libraryType')

        if libraryType == PLEX_LIBRARY_TYPE_COLLECTION:
            if not isinstance(plexItem, collection.Collection):
                return False
        elif not isinstance(plexItem, video.Video):
            return False

        if not plexItem.type == libraryType:
            return False

        plexMediaClass = Api.getPlexMediaClassFromLibraryType(libraryType)
        if not plexMediaClass:
            return False

        return isinstance(plexItem, plexMediaClass)

    @staticmethod
    def MillisecondsToSeconds(milliseconds: float) -> float:
        """Convert milliseconds to seconds

        :param milliseconds: Time in milliseconds
        :type milliseconds: float
        :return: Time in seconds
        :rtype: float
        """
        if not milliseconds:
            return 0.0

        return milliseconds / 1000

    @staticmethod
    def convertDateTimeToDbDate(dateTime: datetime.datetime) -> str:
        """Convert datetime object into '%Y-%m-%d' date only format

        :param dateTime: Datetime object to convert
        :type dateTime: :class:`datetime.datetime`
        :return: Date in string format
        :rtype: str
        """
        if not dateTime:
            return ''

        try:
            return dateTime.strftime('%Y-%m-%d')
        except ValueError:
            return ''

    @staticmethod
    def convertDateTimeToDbDateTime(dateTime: datetime.datetime) -> str:
        """Convert datetime object into '%Y-%m-%d %H:%M:%S' datetime format

        :param dateTime: Datetime object to convert
        :type dateTime: :class:`datetime.datetime`
        :return: DateTime in string format
        :rtype: str
        """
        if not dateTime:
            return ''

        try:
            return dateTime.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            return ''

    @staticmethod
    def ListFromString(string: str) -> List[str]:
        """Convert semi-colon deliminated string into a list of strings

        :param string: String to convert
        :type string: str
        :return: List of clean sub-strings
        :rtype: list
        """
        if not string:
            return []

        return [stringPart.strip() for stringPart in string.split(';')]

    @staticmethod
    def ListFromMediaTags(mediaTags: List[plexapi.media.MediaTag]) -> List[str]:
        """Convert list of `plexapi.media.MediaTag` objects into a list of the tag names

        :param mediaTags: List of `plexapi.media.MediaTag` to parse
        :type mediaTags: list
        :return: List of the tag name strings
        :rtype: list
        """
        if not mediaTags:
            return []

        return [mediaTag.tag.strip() for mediaTag in mediaTags]

    @staticmethod
    def getItemIdFromListItem(listItem: ListItem) -> int:
        """Get the item ID from a ListItem object

        :param listItem: ListItem object to get the ID of
        :type listItem: :class:`ListItem`
        :return: ID of the item
        :rtype: int
        """
        if not listItem:
            raise ValueError('invalid listItem')

        videoInfoTag = listItem.getVideoInfoTag()
        if not videoInfoTag:
            return None

        return Api.getItemIdFromVideoInfoTag(videoInfoTag)

    @staticmethod
    # pylint: disable=too-many-return-statements
    def getItemIdFromVideoInfoTag(videoInfoTag: xbmc.InfoTagVideo) -> int:
        """Get the item ID from a InfoTagVideo object

        :param videoInfoTag: InfoTagVideo object to get the ID of
        :type videoInfoTag: :class:`xbmc.InfoTagVideo`
        :return: ID of the item
        :rtype: int
        """
        if not videoInfoTag:
            raise ValueError('invalid videoInfoTag')

        plexItemId = videoInfoTag.getUniqueID(PLEX_PROTOCOL)
        if plexItemId:
            return int(plexItemId)

        # try to get the database Identifier
        dbId = videoInfoTag.getDbId()
        if not dbId:
            return None

        mediaType = videoInfoTag.getMediaType()
        if mediaType == xbmcmediaimport.MediaTypeMovie:
            method = 'Movie'
        elif mediaType == xbmcmediaimport.MediaTypeTvShow:
            method = 'TVShow'
        elif mediaType == xbmcmediaimport.MediaTypeEpisode:
            method = 'Episode'
        elif mediaType == xbmcmediaimport.MediaTypeMusicVideo:
            method = 'MusicVideo'
        else:
            return None

        # use JSON-RPC to retrieve all unique IDs
        jsonResponse = json.loads(xbmc.executeJSONRPC(json.dumps(
            {
                'jsonrpc': '2.0',
                'method': 'VideoLibrary.Get{}Details'.format(method),
                'params': {
                    '{}id'.format(mediaType): dbId,
                    'properties': ['uniqueid'],
                },
                'id': 0
            })))
        if not jsonResponse or 'result' not in jsonResponse:
            return None

        jsonResult = jsonResponse['result']
        detailsKey = '{}details'.format(mediaType)
        if detailsKey not in jsonResult:
            return None

        jsonDetails = jsonResult[detailsKey]
        if 'uniqueid' not in jsonDetails:
            return None

        jsonUniqueIDs = jsonDetails['uniqueid']
        if PLEX_PROTOCOL not in jsonUniqueIDs:
            return None

        return int(jsonUniqueIDs[PLEX_PROTOCOL])

    @staticmethod
    def getItemIdFromPlexKey(plexItemKey: str) -> int:
        """Get the item ID from a plex XML key

        :param plexItemKey: Plex XML item key to parse the ID of
        :type plexItemKey: str
        :return: Parsed ID
        :rtype: int
        """
        parts = plexItemKey.split('/')
        if not parts:
            return 0

        return int(parts[-1])

    @staticmethod
    def getPlexMediaClassFromMediaType(mediaType: str) -> video.Video:
        """Get the plexapi video obejct type matching the provided Kodi media type

        :param mediaType: Kodi Media type object
        :type mediaType: str
        :return: Plex media class obejct matching the provided media type
        :rtype: :class:`video.Video`
        """
        mappedMediaType = Api.getPlexMediaType(mediaType)
        if not mappedMediaType:
            return None

        return Api.getPlexMediaClassFromLibraryType(mappedMediaType['libtype'])

    @staticmethod
    def getPlexMediaClassFromLibraryType(libraryType: str) -> video.Video:
        """Get the plexapi vode object type matching the provided Plex library type

        :param libraryType: Type of plex library (movie, show, season, episode, collection)
        :type libraryType: str
        :return: Plex media class obejct matching the provided media type
        :rtype: :class:`video.Video`
        """
        if libraryType == PLEX_LIBRARY_TYPE_MOVIE:
            return video.Movie
        if libraryType == PLEX_LIBRARY_TYPE_TVSHOW:
            return video.Show
        if libraryType == PLEX_LIBRARY_TYPE_SEASON:
            return video.Season
        if libraryType == PLEX_LIBRARY_TYPE_EPISODE:
            return video.Episode
        if libraryType == PLEX_LIBRARY_TYPE_COLLECTION:
            return collection.Collection

        return None

    @staticmethod
    def getPlexMediaClassFromListItem(item: ListItem) -> video.Video:
        """Get the plexapi video obejct type matching the provided ListItem

        :param item: ListItem
        :type item: :class:`xbmcgui.ListItem`
        :return: Plex media class obejct matching the provided media type
        :rtype: :class:`video.Video`
        """
        if not item:
            raise ValueError('invalid item')

        videoInfoTag = item.getVideoInfoTag()
        if not videoInfoTag:
            return None

        return Api.getPlexMediaClassFromVideoInfoTag(videoInfoTag)

    @staticmethod
    def getPlexMediaClassFromVideoInfoTag(videoInfoTag: xbmc.InfoTagVideo) -> video.Video:
        """Get the plexapi video obejct type matching the provided InfoTagVideo

        :param videoInfoTag: InfoTagVideo object
        :type videoInfoTag: :class:`xbmc.InfoTagVideo`
        :return: Plex media class obejct matching the provided media type
        :rtype: :class:`video.Video`
        """
        if not videoInfoTag:
            raise ValueError('invalid videoInfoTag')

        return Api.getPlexMediaClassFromMediaType(videoInfoTag.getMediaType())

    @staticmethod
    def getPlexItemDetails(
            plexServer: server.PlexServer,
            plexItemId: int,
            plexItemClass: video.Video = None
    ) -> video.Video:
        """Get details of Plex item from the specified server by its ID

        :param plexServer: Plex server object to interact with
        :type plexServer: :class:`server.PlexServer`
        :param plexItemId: ID of the item to retreive from the server
        :type plexItemId: int
        :param plexItemClass: Plex video object to populate
        :type plexItemClass: :class:`video.Video`, optional
        :return: Populated video object with details of the item
        :rtype: :class:`video.Video`
        """
        if not plexServer:
            raise ValueError('invalid plexServer')
        if not plexItemId:
            raise ValueError('invalid plexItemId')

        plexLibrary = plexServer.library
        if not plexLibrary:
            raise ValueError('plexServer does not contain a library')

        return plexLibrary.fetchItem(plexItemId, cls=plexItemClass)

    @staticmethod
    def getPlexItemAsListItem(
            plexServer: server.PlexServer,
            plexItemId: int,
            plexItemClass: video.Video = None,
            allowDirectPlay: bool = False
    ) -> ListItem:
        """Get details of Plex item from the specified server by its ID and conver to xbmcgui ListItem object

        :param plexServer: Plex server object to interact with
        :type plexServer: :class:`server.PlexServer`
        :param plexItemId: ID of the item to retreive from the server
        :type plexItemId: int
        :param plexItemClass: Plex video object to populate
        :type plexItemClass: :class:`video.Video`, optional
        :param allowDirectPlay: Settings definition on provider if directPlay is allowed
        :type allowDirectPlay: bool, optional
        :return: ListItem object populated with the retreived plex item details
        :rtype: :class:`ListItem`
        """
        if not plexServer:
            raise ValueError('invalid plexServer')
        if not plexItemId:
            raise ValueError('invalid plexItemId')

        plexItem = Api.getPlexItemDetails(plexServer, plexItemId, plexItemClass)
        if not plexItem:
            return None

        return Api.toFileItem(plexServer, plexItem, allowDirectPlay=allowDirectPlay)

    @staticmethod
    def canPlay(plexItem: video.Video) -> bool:
        if not plexItem:
            raise ValueError('invalid plexItem')

        if isinstance(plexItem, (video.Movie, video.Episode)) and plexItem.media:
            return True

        return False

    @staticmethod
    def getDirectPlayUrlFromPlexItem(plexItem: video.Video) -> str:
        if not plexItem:
            raise ValueError('invalid plexItem')

        if not Api.canPlay(plexItem):
            return None

        for media in plexItem.media:
            if not media:
                continue

            # try to get a direct play URL
            directPlayUrl = Api.getDirectPlayUrlFromMedia(media)
            if directPlayUrl:
                return directPlayUrl

        return None

    @staticmethod
    def getDirectPlayUrlFromMedia(media: media.Media) -> str:
        if not media:
            raise ValueError('invalid media')

        for mediaPart in media.parts:
            # try to get a direct play URL
            directPlayUrl = Api.getDirectPlayUrl(mediaPart)
            if directPlayUrl:
                return directPlayUrl

        return None

    @staticmethod
    def getDirectPlayUrl(mediaPart: media.MediaPart) -> str:
        if not mediaPart:
            raise ValueError('invalid mediaPart')

        # extract the absolute / actual path and the stream URL from the given MediaPart
        path = mediaPart.file

        # if we can access the direct path we can use Direct Play
        if xbmcvfs.exists(path):
            return path

        # perform replacement in file path if configured
        mappedPath = Api._mapPath(path)

        # confirm file is accessible and store item path
        if mappedPath and xbmcvfs.exists(mappedPath):
            return mappedPath

        return None

    @staticmethod
    def getStreamUrlFromPlexItem(plexItem: video.Video, plexServer: server.PlexServer) -> str:
        if not plexItem:
            raise ValueError('invalid plexItem')

        if not Api.canPlay(plexItem):
            return None

        for media in plexItem.media:
            if not media:
                continue

            return Api.getStreamUrlFromMedia(media, plexServer)

        return None

    @staticmethod
    def getStreamUrlFromMedia(media: media.Media, plexServer: server.PlexServer) -> str:
        if not media:
            raise ValueError('invalid media')

        for mediaPart in media.parts:
            return Api.getStreamUrl(mediaPart, plexServer)

        return None


    @staticmethod
    def getStreamUrl(mediaPart: media.MediaPart, plexServer: server.PlexServer) -> str:
        if not mediaPart:
            raise ValueError('invalid mediaPart')
        if not plexServer:
            raise ValueError('invalid plexServer')

        return plexServer.url(mediaPart.key, includeToken=True)

    @staticmethod
    def toFileItem(
            plexServer: server.PlexServer,
            plexItem: video.Video,
            mediaType: str = None,
            plexLibType: str = None,
            allowDirectPlay: bool = False
    ) -> ListItem:
        """Validate, populate, and convert the provided plexItem into a Kodi GUI ListItem object

        :param plexServer: Plex server to gather additional details from
        :type plexServer: server.PlexServer
        :param plexItem: Plex object populated with information about the item
        :type plexItem: video.Video
        :param mediaType: Kodi Media type object, defaults to ''
        :type mediaType: str, optional
        :param plexLibType: Type of plex library (movie, show, season, episode, collection), defaults to ''
        :type plexLibType: str, optional
        :param allowDirectPlay: Settings definition on provider if directPlay is allowed
        :type allowDirectPlay: bool, optional
        :return: ListItem object populated with the retreived plex item details
        :rtype: ListItem
        """
        # determine the matching Plex library type if possible
        checkMediaType = mediaType is not None
        if checkMediaType and not plexLibType:
            mappedMediaType = Api.getPlexMediaType(mediaType)
            if not mappedMediaType:
                log(f"cannot import unsupported media type '{mediaType}'", xbmc.LOGERROR)
                return None

            plexLibType = mappedMediaType['libtype']

        # make sure the item matches the media type
        if plexLibType and not Api.validatePlexLibraryItemType(plexItem, plexLibType):
            log(f"cannot import {mediaType} item from invalid Plex library item: {plexItem}", xbmc.LOGERROR)
            return None

        # determine the Kodi media type based on the Plex library type
        if not checkMediaType:
            plexLibType = plexItem.type
            mappedMediaTypes = Api.getKodiMediaTypesFromPlexLibraryType(plexLibType)
            if not mappedMediaTypes:
                log(f"cannot import unsupported Plex library type '{plexLibType}'", xbmc.LOGERROR)
                return None

            if len(mappedMediaTypes) > 1:
                log(
                    f"{len(mappedMediaTypes)} supported media type for Plex library type '{plexLibType}'",
                    xbmc.LOGDEBUG
                )

            mediaType = mappedMediaTypes[0]['kodi']

        itemId = plexItem.ratingKey
        if not itemId:
            log(f"cannot import {mediaType} item without identifier", xbmc.LOGERROR)
            return None

        item = ListItem(label=plexItem.title, offscreen=True)

        # fill video details
        Api.fillVideoInfos(plexServer, itemId, plexItem, mediaType, item, allowDirectPlay)

        if not item.getPath():
            log(f"failed to retrieve a path for {mediaType} item '{item.getLabel()}'", xbmc.LOGWARNING)
            return None

        return item

    @staticmethod
    def fillVideoInfos(
            plexServer: server.PlexServer,
            itemId: int,
            plexItem: video.Video,
            mediaType: str,
            item: ListItem,
            allowDirectPlay: bool = False
    ):
        """
        Populate the provided ListItem object with existing data from plexItem
        and additional detail pulled from the provided plexServer

        :param plexServer: Plex server to gather additional details from
        :type plexServer: server.PlexServer
        :param itemId: Unique ID of the plex Video object item
        :type itemId: int
        :param plexItem: Plex object populated with information about the item
        :type plexItem: video.Video
        :param mediaType: Kodi Media type object
        :type mediaType: str
        :param item: Instantiated Kodi ListItem to populate with additional details
        :type item: :class:`ListItem`
        :param allowDirectPlay: Settings definition on provider if directPlay is allowed
        :type allowDirectPlay: bool, optional
        """
        videoInfoTag = item.getVideoInfoTag()

        videoInfoTag.setMediaType(mediaType)
        videoInfoTag.setTitle(item.getLabel() or '')

        date = None
        isFolder = False

        resumeTime = 0.0
        duration = 0.0

        artwork = {}
        collections = []
        media = []
        locations = []
        roles = []

        if isinstance(plexItem, video.Video):
            videoInfoTag.setSortTitle(plexItem.titleSort or '')
            videoInfoTag.setPlot(plexItem.summary or '')
            videoInfoTag.setDateAdded(Api.convertDateTimeToDbDateTime(plexItem.addedAt))
            videoInfoTag.setPlaycount(plexItem.viewCount or 0)
            videoInfoTag.setLastPlayed(Api.convertDateTimeToDbDateTime(plexItem.lastViewedAt))
            videoInfoTag.setTags([plexItem.librarySectionTitle])

        if isinstance(plexItem, video.Movie):
            date = Api.convertDateTimeToDbDate(plexItem.originallyAvailableAt)
            duration = Api.MillisecondsToSeconds(plexItem.duration)
            resumeTime = Api.MillisecondsToSeconds(plexItem.viewOffset)
            collections = plexItem.collections or []
            media = plexItem.media or []
            roles = plexItem.roles or []

            videoInfoTag.setMpaa(plexItem.contentRating or '')
            videoInfoTag.setDuration(int(duration))
            videoInfoTag.setOriginalTitle(plexItem.originalTitle or '')
            videoInfoTag.setPremiered(date)
            videoInfoTag.setRating(plexItem.rating or 0.0)
            videoInfoTag.setTagLine(plexItem.tagline or '')
            videoInfoTag.setUserRating(int(plexItem.userRating or 0))
            videoInfoTag.setYear(plexItem.year or 0)
            videoInfoTag.setStudios(Api.ListFromString(plexItem.studio))
            videoInfoTag.setCountries(Api.ListFromMediaTags(plexItem.countries))
            videoInfoTag.setGenres(Api.ListFromMediaTags(plexItem.genres))
            videoInfoTag.setDirectors(Api.ListFromMediaTags(plexItem.directors))
            videoInfoTag.setWriters(Api.ListFromMediaTags(plexItem.writers))
        elif isinstance(plexItem, collection.Collection):
            # ignore empty collections
            if plexItem.childCount <= 0:
                return

            isFolder = True

            videoInfoTag.setPlot(plexItem.summary or '')
            videoInfoTag.setDateAdded(Api.convertDateTimeToDbDateTime(plexItem.addedAt))
        elif isinstance(plexItem, video.Show):
            isFolder = True
            date = Api.convertDateTimeToDbDate(plexItem.originallyAvailableAt)
            duration = Api.MillisecondsToSeconds(plexItem.duration)
            locations = plexItem.locations or []
            collections = plexItem.collections or []
            roles = plexItem.roles or []

            banner = plexItem.banner
            if banner:
                artwork['banner'] = plexServer.url(banner, includeToken=True)

            videoInfoTag.setMpaa(plexItem.contentRating or '')
            videoInfoTag.setDuration(int(duration))
            videoInfoTag.setOriginalTitle(plexItem.originalTitle or '')
            videoInfoTag.setPremiered(date)
            videoInfoTag.setRating(plexItem.rating or 0.0)
            videoInfoTag.setTagLine(plexItem.tagline or '')
            videoInfoTag.setYear(plexItem.year or 0)
            videoInfoTag.setStudios(Api.ListFromString(plexItem.studio))
            videoInfoTag.setGenres(Api.ListFromMediaTags(plexItem.genres))
        elif isinstance(plexItem, video.Season):
            isFolder = True

            videoInfoTag.setTvShowTitle(plexItem.parentTitle or '')
            videoInfoTag.setSeason(plexItem.index)
        elif isinstance(plexItem, video.Episode):
            date = Api.convertDateTimeToDbDate(plexItem.originallyAvailableAt)
            resumeTime = Api.MillisecondsToSeconds(plexItem.viewOffset)
            duration = Api.MillisecondsToSeconds(plexItem.duration)
            media = plexItem.media or []

            videoInfoTag.setTvShowTitle(plexItem.grandparentTitle or '')
            videoInfoTag.setSeason(int(plexItem.parentIndex))
            videoInfoTag.setEpisode(plexItem.index)
            videoInfoTag.setMpaa(plexItem.contentRating or '')
            videoInfoTag.setDuration(int(duration))
            videoInfoTag.setFirstAired(date)
            videoInfoTag.setRating(plexItem.rating or 0.0)
            videoInfoTag.setYear(plexItem.year or 0)
            videoInfoTag.setDirectors(Api.ListFromMediaTags(plexItem.directors))
            videoInfoTag.setWriters(Api.ListFromMediaTags(plexItem.writers))

        # handle collections / sets
        collections = Api.ListFromMediaTags(collections)
        if collections:
            # Kodi can only store one set per media item
            videoInfoTag.setSet(collections[0])

        # set the item's datetime if available
        if date:
            item.setDateTime(date)

        # specify whether the item is a folder or not
        item.setIsFolder(isFolder)

        # add the item's ID as a unique ID belonging to Plex
        uniqueIDs = {
            PLEX_PROTOCOL: str(itemId)
        }
        # retrieve and map GUIDS from Plex
        if isinstance(plexItem, (video.Movie, video.Show, video.Season, video.Episode)):
            guids = Api._mapGuids(plexItem.guids)
            if guids:
                uniqueIDs = {**guids, **uniqueIDs}

        videoInfoTag.setUniqueIDs(uniqueIDs, PLEX_PROTOCOL)

        # handle actors / cast
        cast = []
        for index, role in enumerate(roles):
            actor = xbmc.Actor(role.tag.strip(), (role.role or '').strip(), index, role.thumb)
            cast.append(actor)
        if cast:
            videoInfoTag.setCast(cast)

        # handle resume point
        if resumeTime > 0 and duration > 0.0:
            videoInfoTag.setResumePoint(resumeTime, duration)

        # handle stream details
        path = None
        for mediaStream in media:
            for part in mediaStream.parts:
                # pick the first MediaPart with a valid file and stream URL
                if not path and part.file and part.key:
                    path = part.file

                for videoStream in part.videoStreams():
                    videoInfoTag.addVideoStream(xbmc.VideoStreamDetail(
                        width=videoStream.width or 0,
                        height=videoStream.height or 0,
                        codec=videoStream.codec or '',
                        duration=int(duration),
                        language=videoStream.language or ''
                    ))

                for audioStream in part.audioStreams():
                    videoInfoTag.addAudioStream(xbmc.AudioStreamDetail(
                        channels=audioStream.channels or 2,
                        codec=audioStream.codec or '',
                        language=audioStream.language or ''
                    ))

                for index, subtitleStream in enumerate(part.subtitleStreams()):
                    videoInfoTag.addSubtitleStream(xbmc.SubtitleStreamDetail(
                        language=subtitleStream.language or f"[{index}]"
                    ))

        if isFolder:
            # for folders use locations for the path
            if locations:
                path = locations[0]
            item.setPath(plexServer.url(plexItem.key, includeToken=True))
        else:
            # determine if directPlay is enabled and possible
            if allowDirectPlay:
                directPlayUrl = Api.getDirectPlayUrlFromPlexItem(plexItem)
                if directPlayUrl:
                    item.setPath(directPlayUrl)

            # otherwise determine the stream URL
            if not item.getPath():
                item.setPath(Api.getStreamUrlFromPlexItem(plexItem, plexServer))

        if path:
            videoInfoTag.setPath(path)
        videoInfoTag.setFilenameAndPath(item.getPath())

        # handle artwork
        poster = None
        fanart = None
        if isinstance(plexItem, video.Video):
            poster = plexItem.thumbUrl
            fanart = plexItem.artUrl
        elif isinstance(plexItem, collection.Collection) and plexItem.thumb:
            poster = plexServer.url(plexItem.thumb, includeToken=True)

        if poster:
            artwork['poster'] = poster
        if fanart:
            artwork['fanart'] = fanart
        if artwork:
            item.setArt(artwork)

    @staticmethod
    def _mapPath(path: str) -> str:
        """Replace and standardizes Windows UNC paths for Kodi consumption

        :param path: Currenty path to process for UNC fixes
        :type path: str
        :return: Standardized path that Kodi can consume
        :rtype: str
        """
        if not path:
            return ''

        # turn UNC paths into Kodi-specific Samba paths
        if path.startswith('\\\\'):
            path = path.replace('\\\\', 'smb://', 1).replace('\\\\', '\\').replace('\\', '/')

        # get rid of any double backslashes
        path = path.replace('\\\\', '\\')

        # make sure paths are consistent
        if '\\' in path:
            path.replace('/', '\\')

        return path

    @staticmethod
    def _mapGuids(guids: List[plexapi.media.Guid]) -> dict:
        guidMap = {}
        if not guids:
            return guidMap

        for guid in guids:
            try:
                parsedGuid = urlparse(guid.id)
                if parsedGuid.scheme and parsedGuid.netloc:
                    guidMap[parsedGuid.scheme] = parsedGuid.netloc
            except ValueError:
                pass

        return guidMap
