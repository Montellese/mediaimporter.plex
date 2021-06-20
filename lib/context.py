#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2021 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import sys

import xbmc  # pylint: disable=import-error
import xbmcmediaimport  # pylint: disable=import-error
from xbmcgui import Dialog, ListItem  # pylint: disable=import-error

from lib.utils import bitrate2str, localize, log, mediaProvider2str
from plex.api import Api
from plex.constants import SETTINGS_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY
from plex.server import Server

import plexapi
from plexapi import collection, media, video


PLAY_MULTIPLE_VERSIONS_KEY = 'mediaimporter.plex/multiple_versions'


class ContextAction:
    Play = 0
    Synchronize = 1
    RefreshMetadata = 2


def contextLog(message: str, level: int = xbmc.LOGINFO, entry: str = None):
    logName = 'context'
    if entry:
        logName = f"{logName}/{entry}"

    log(f"[{logName}] {message}", level)


def listItem2str(item: ListItem, itemId: int) -> str:
    return f'"{item.getLabel()}" ({itemId})'


def getMediaImport(mediaProvider: xbmcmediaimport.MediaProvider, item: ListItem) -> xbmcmediaimport.MediaImport:
    videoInfoTag = item.getVideoInfoTag()
    if not videoInfoTag:
        return None

    mediaType = videoInfoTag.getMediaType()
    if not mediaType:
        return None

    mediaImports = mediaProvider.getImports()
    return next((mediaImport for mediaImport in mediaImports if mediaType in mediaImport.getMediaTypes()), None)


def synchronizeItem(
    item: ListItem,
    itemId: int,
    mediaProvider: xbmcmediaimport.MediaProvider,
    plexServer: plexapi.server.PlexServer,
    plexItemClass: video.Video = None,
    allowDirectPlay: bool = True) -> ListItem:

    # retrieve all details of the item
    fullItem = Api.getPlexItemAsListItem(plexServer, itemId, plexItemClass=plexItemClass, allowDirectPlay=allowDirectPlay)
    if not fullItem:
        contextLog(f"cannot retrieve details of {listItem2str(item, itemId)} from {mediaProvider2str(mediaProvider)}",
        xbmc.LOGERROR, entry='sync')
        return None

    return fullItem


def play(item, itemId, mediaProvider):
    if item.isFolder():
        contextLog(f"cannot play folder item {listItem2str(item, itemId)}", xbmc.LOGERROR, entry='play')
        return

    # create a Plex server instance
    server = Server(mediaProvider)
    if not server.Authenticate():
        contextLog(
            f"failed to connect to Plex Media Server for {mediaProvider2str(mediaProvider)}",
            xbmc.LOGWARNING, entry='sync')
        return

    plexItemClass = Api.getPlexMediaClassFromListItem(item)

    # cannot play folders
    if plexItemClass in (collection.Collection, video.Show, video.Season):
        contextLog(f"cannot play folder item {listItem2str(item, itemId)}", xbmc.LOGERROR, entry='play')
        return

    # get the Plex item with all its details
    plexItem = Api.getPlexItemDetails(server.PlexServer(), itemId, plexItemClass=plexItemClass)
    if not plexItem:
        contextLog(
            f"failed to determine Plex item for {listItem2str(item, itemId)} from {mediaProvider2str(mediaProvider)}",
            xbmc.LOGWARNING, entry='refresh')
        return

    # cannot play folders
    if not Api.canPlay(plexItem):
        contextLog(f"cannot play item {listItem2str(item, itemId)}", xbmc.LOGERROR, entry='play')
        return

    playChoices = []
    playChoicesUrl = []

    # determine whether Direct Play is allowed
    mediaProviderSettings = mediaProvider.getSettings()
    allowDirectPlay = mediaProviderSettings.getBool(SETTINGS_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY)

    # check if the item supports Direct Play
    if allowDirectPlay:
        directPlayUrl = Api.getDirectPlayUrlFromPlexItem(plexItem)
        if directPlayUrl:
            playChoices.append(localize(32103))
            playChoicesUrl.append(directPlayUrl)

    # check if the item supports streaming
    directStreamUrl = Api.getStreamUrlFromPlexItem(plexItem, server.PlexServer())
    if directStreamUrl:
        playChoices.append(localize(32104))
        playChoicesUrl.append(directStreamUrl)

    # check if the item has multiple versions
    multipleVersions = []
    if len(plexItem.media) > 1:
        for mediaStream in plexItem.media:
            url = None
            if allowDirectPlay:
                directPlayUrl = Api.getDirectPlayUrlFromMedia(mediaStream)
                if directPlayUrl:
                    url = directPlayUrl

            if not url:
                url = Api.getStreamUrlFromMedia(mediaStream, server.PlexServer())

            # get the display title of the first videostream
            for mediaPart in mediaStream.parts:
                # get all video streams
                videoStreams = (stream for stream in mediaPart.streams if isinstance(stream, media.VideoStream))
                # extract the first non-empty display resolution
                displayResolution = next(
                    (
                        stream.displayTitle or stream.extendedDisplayTitle
                        for stream in videoStreams
                        if stream.displayTitle or stream.extendedDisplayTitle
                    ),
                    None)
                if displayResolution:
                    break

            # fall back to the basic video resolution of the stream
            if not displayResolution:
                displayResolution = mediaStream.videoResolution

            multipleVersions.append((url, mediaStream.bitrate, displayResolution))

    if len(multipleVersions) > 1:
        playChoices.append(localize(32105))
        playChoicesUrl.append(PLAY_MULTIPLE_VERSIONS_KEY)

    # if there are no options something went wrong
    if not playChoices:
        contextLog(
            f"cannot play {listItem2str(item, itemId)} from {mediaProvider2str(mediaProvider)}",
            xbmc.LOGERROR, entry='play')
        return

    # ask the user how to play
    playChoice = Dialog().contextmenu(playChoices)
    if playChoice < 0 or playChoice >= len(playChoices):
        return

    playUrl = playChoicesUrl[playChoice]

    # check if the user chose to choose which version to play
    if playUrl == PLAY_MULTIPLE_VERSIONS_KEY:
        playChoices.clear()
        playChoicesUrl.clear()

        # sort the available versions by bitrate (second field)
        multipleVersions.sort(key=lambda version: version[1], reverse=True)

        for version in multipleVersions:
            playChoices.append(
                localize(32106, bitrate=bitrate2str(version[1]), resolution=version[2]))
            playChoicesUrl.append(version[0])

        # ask the user which version to play
        playChoice = Dialog().contextmenu(playChoices)
        if playChoice < 0 or playChoice >= len(playChoices):
            return

        playUrl = playChoicesUrl[playChoice]

    # play the item
    contextLog(
        (
            f'playing {listItem2str(item, itemId)} using "{playChoices[playChoice]}" ({playUrl}) '
            f'from {mediaProvider2str(mediaProvider)}'
        ),
        entry='play')
    # overwrite the dynamic path of the ListItem
    item.setDynamicPath(playUrl)
    xbmc.Player().play(playUrl, item)


def synchronize(item: ListItem, itemId: int, mediaProvider):
    # find the matching media import
    mediaImport = getMediaImport(mediaProvider, item)
    if not mediaImport:
        contextLog(
            f"cannot find the media import of {listItem2str(item, itemId)} from {mediaProvider2str(mediaProvider)}",
            xbmc.LOGERROR, entry='sync')
        return

    # determine whether Direct Play is allowed
    mediaProviderSettings = mediaProvider.getSettings()
    allowDirectPlay = mediaProviderSettings.getBool(SETTINGS_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY)

    # create a Plex server instance
    server = Server(mediaProvider)
    if not server.Authenticate():
        contextLog(
            f"failed to connect to Plex Media Server for {mediaProvider2str(mediaProvider)}",
            xbmc.LOGWARNING, entry='sync')
        return

    plexItemClass = Api.getPlexMediaClassFromListItem(item)

    # synchronize the active item
    syncedItem = synchronizeItem(item, itemId, mediaProvider, server.PlexServer(), plexItemClass=plexItemClass,
                                 allowDirectPlay=allowDirectPlay)
    if not syncedItem:
        return
    syncedItems = [(xbmcmediaimport.MediaImportChangesetTypeChanged, syncedItem)]

    if xbmcmediaimport.changeImportedItems(mediaImport, syncedItems):
        contextLog(f"synchronized {listItem2str(item, itemId)} from {mediaProvider2str(mediaProvider)}", entry='sync')
    else:
        contextLog(
            f"failed to synchronize {listItem2str(item, itemId)} from {mediaProvider2str(mediaProvider)}",
            xbmc.LOGWARNING, entry='sync')


def refreshMetadata(item: ListItem, itemId: int, mediaProvider: xbmcmediaimport.MediaProvider):
    # create a Plex server instance
    server = Server(mediaProvider)
    if not server.Authenticate():
        contextLog(
            f"failed to connect to Plex Media Server for {mediaProvider2str(mediaProvider)}",
            xbmc.LOGWARNING, entry='refresh')
        return

    plexItemClass = Api.getPlexMediaClassFromListItem(item)

    # get the Plex item with all its details
    plexItem = Api.getPlexItemDetails(server.PlexServer(), itemId, plexItemClass=plexItemClass)
    if not plexItem:
        contextLog(
            f"failed to determine Plex item for {listItem2str(item, itemId)} from {mediaProvider2str(mediaProvider)}",
            xbmc.LOGWARNING, entry='refresh')
        return
    # trigger a metadata refresh on the Plex server
    plexItem.refresh()
    contextLog(
        f"triggered metadata refresh for {listItem2str(item, itemId)} on {mediaProvider2str(mediaProvider)}",
        entry="refresh")


def run(action):
    item = sys.listitem  # pylint: disable=no-member
    if not item:
        contextLog('missing ListItem', xbmc.LOGERROR)
        return

    itemId = Api.getItemIdFromListItem(item)
    if not itemId:
        contextLog(f'cannot determine the Emby identifier of "{item.getLabel()}"', xbmc.LOGERROR)
        return

    mediaProviderId = item.getMediaProviderId()
    if not mediaProviderId:
        contextLog(f"cannot determine the media provider identifier of {listItem2str(item, itemId)}", xbmc.LOGERROR)
        return

    # get the media provider
    mediaProvider = xbmcmediaimport.getProviderById(mediaProviderId)
    if not mediaProvider:
        contextLog(
            f"cannot determine the media provider ({mediaProviderId}) of {listItem2str(item, itemId)}", xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        contextLog(
            f"cannot prepare media provider ({mediaProvider2str(mediaProvider)}) settings of {listItem2str(item, itemId)}",
            xbmc.LOGERROR)
        return

    if action == ContextAction.Play:
        play(item, itemId, mediaProvider)
    elif action == ContextAction.Synchronize:
        synchronize(item, itemId, mediaProvider)
    elif action == ContextAction.RefreshMetadata:
        refreshMetadata(item, itemId, mediaProvider)
    else:
        raise ValueError(f"unknown action {action}")
