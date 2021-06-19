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
from xbmcgui import ListItem  # pylint: disable=import-error

from lib.utils import log, mediaProvider2str
from plex.api import Api
from plex.constants import SETTINGS_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY
from plex.server import Server

import plexapi
from plexapi import video


class ContextAction:
    Synchronize = 0
    RefreshMetadata = 1


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

    if action == ContextAction.Synchronize:
        synchronize(item, itemId, mediaProvider)
    elif action == ContextAction.RefreshMetadata:
        refreshMetadata(item, itemId, mediaProvider)
    else:
        raise ValueError(f"unknown action {action}")
