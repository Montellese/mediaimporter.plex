#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import json

import xbmc
import xbmcmediaimport

from plex.api import *
from plex.constants import *
from plex.server import Server

import lib.websocket
from lib.utils import log, mediaImport2str, mediaProvider2str, Url

class ProviderObserver:
    class Action:
        Start = 0
        Stop = 1

    ENDPOINT = '/:/websockets/notifications'

    def __init__(self):
        # default values
        self._actions = []
        self._connected = False
        self._imports = []
        self._mediaProvider = None
        self._server = None

        # create the websocket
        self._websocket = lib.websocket.WebSocket()
        self._websocket.settimeout(0.1)

    def __del__(self):
        self._StopAction()

    def AddImport(self, mediaImport):
        if not mediaImport:
            raise ValueError('invalid mediaImport')

        # look for a matching import
        matchingImportIndices = self._FindImportIndices(mediaImport)
        # if a matching import has been found update it
        if matchingImportIndices:
            self._imports[matchingImportIndices[0]] = mediaImport
            log('media import {} updated'.format(mediaImport2str(mediaImport)))
        else:
            # other add the import to the list
            self._imports.append(mediaImport)
            log('media import {} added'.format(mediaImport2str(mediaImport)))

    def RemoveImport(self, mediaImport):
        if not mediaImport:
            raise ValueError('invalid mediaImport')

        # look for a matching import
        matchingImportIndices = self._FindImportIndices(mediaImport)
        if not matchingImportIndices:
            return

        # remove the media import from the list
        del self._imports[matchingImportIndices[0]]
        log('media import {} removed'.format(mediaImport2str(mediaImport)))

    def Start(self, mediaProvider):
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        self._actions.append((ProviderObserver.Action.Start, mediaProvider))

    def Stop(self):
        self._actions.append((ProviderObserver.Action.Stop, None))

    def Process(self):
        # process any open actions
        self._ProcessActions()
        # process any incoming messages
        self._ProcessMessages()

    def _FindImportIndices(self, mediaImport):
        if not mediaImport:
            raise ValueError('invalid mediaImport')

        return [ i for i, x in enumerate(self._imports) if x.getPath() == mediaImport.getPath() and x.getMediaTypes() == mediaImport.getMediaTypes() ]

    def _ProcessActions(self):
        for (action, data) in self._actions:
            if action == ProviderObserver.Action.Start:
                self._StartAction(data)
            elif action == ProviderObserver.Action.Stop:
                self._StopAction()
            else:
                log('unknown action {} to process'.format(action), xbmc.LOGWARNING)

        self._actions = []

    def _ProcessMessages(self):
        # nothing to do if we are not connected to an Emby server
        if not self._connected:
            return

        while True:
            try:
                message = self._websocket.recv()
                if message is None:
                    break

                messageObj = json.loads(message)
                if not messageObj:
                    log('invalid JSON message ({}) from {} received: {}'.format(len(message), mediaProvider2str(self._mediaProvider), message), xbmc.LOGWARNING)
                    continue

                self._ProcessMessage(messageObj)

            except lib.websocket.WebSocketTimeoutException:
                break
            except Exception as error:
                log('unknown exception when receiving data from {}: {}'.format(mediaProvider2str(self._mediaProvider), error.args[0]), xbmc.LOGWARNING)
                break

    def _ProcessMessage(self, message):
        if not message:
            return

        if not WS_MESSAGE_NOTIFICATION_CONTAINER in message:
            log('message without "{}" received from {}: {}'.format(WS_MESSAGE_NOTIFICATION_CONTAINER, mediaProvider2str(self._mediaProvider), json.dumps(message)), xbmc.LOGWARNING)
            return

        messageData = message[WS_MESSAGE_NOTIFICATION_CONTAINER]
        if not WS_MESSAGE_NOTIFICATION_TYPE in messageData:
            log('message without "{}" received from {}: {}'.format(WS_MESSAGE_NOTIFICATION_TYPE, mediaProvider2str(self._mediaProvider), json.dumps(message)), xbmc.LOGWARNING)
            return

        messageType = messageData[WS_MESSAGE_NOTIFICATION_TYPE]
        if messageType == WS_MESSAGE_NOTIFICATION_TYPE_TIMELINE:
            self._ProcessMessageTimelineEntry(messageData)
        elif messageType == WS_MESSAGE_NOTIFICATION_TYPE_PLAYING:
            self._ProcessMessagePlaySessionState(messageData)
        elif messageType == WS_MESSAGE_NOTIFICATION_TYPE_ACTIVITY:
            self._ProcessMessageActivity(messageData)
        else:
            log('ignoring "{}" message from {}: {}'.format(messageType, mediaProvider2str(self._mediaProvider), json.dumps(message)), xbmc.LOGDEBUG)

    def _ProcessMessageTimelineEntry(self, data):
        if not WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY in data:
            log('invalid timeline message received from {}: {}'.format(mediaProvider2str(self._mediaProvider), json.dumps(data)), xbmc.LOGWARNING)
            return

        timelineEntries = data[WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY]
        if not timelineEntries:
            return

        changedPlexItems = []
        for timelineEntry in timelineEntries:
            if not all(key in timelineEntry for key in (WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_IDENTIFIER, WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_ITEM_ID, WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE, WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_STATE)):
                continue

            # we are only interested in library changes
            if timelineEntry[WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_IDENTIFIER] != WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_IDENTIFIER_LIBRARY:
                continue

            plexItemId = int(timelineEntry[WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_ITEM_ID])
            if not plexItemId:
                continue

            # filter and determine the changed item's library type / class
            plexItemType = timelineEntry[WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE]
            if plexItemType == WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE_MOVIE:
                plexItemLibraryType = PLEX_LIBRARY_TYPE_MOVIE
            elif plexItemType == WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE_TVSHOW:
                plexItemLibraryType = PLEX_LIBRARY_TYPE_TVSHOW
            elif plexItemType == WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE_SEASON:
                plexItemLibraryType = PLEX_LIBRARY_TYPE_SEASON
            elif plexItemType == WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE_EPISODE:
                plexItemLibraryType = PLEX_LIBRARY_TYPE_EPISODE
            else:
                continue
            plexItemMediaClass = Api.getPlexMediaClassFromLibraryType(plexItemLibraryType)

            # filter and process the changed item's state
            plexItemState = timelineEntry[WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_STATE]
            if plexItemState == WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_STATE_CREATED:
                plexItemChangesetType = xbmcmediaimport.MediaImportChangesetTypeAdded
            elif plexItemState == WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_STATE_FINISHED:
                plexItemChangesetType = xbmcmediaimport.MediaImportChangesetTypeChanged
            elif plexItemState == WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_STATE_DELETED:
                plexItemChangesetType = xbmcmediaimport.MediaImportChangesetTypeRemoved
            else:
                continue

            changedPlexItems.append((plexItemChangesetType, plexItemId, plexItemMediaClass))

        self._ProcessChangedPlexItems(changedPlexItems)

    def _ProcessMessagePlaySessionState(self, data):
        if not WS_MESSAGE_NOTIFICATION_PLAY_SESSION_STATE in data:
            log('invalid playing message received from {}: {}'.format(mediaProvider2str(self._mediaProvider), json.dumps(data)), xbmc.LOGWARNING)
            return

        playSessionStates = data[WS_MESSAGE_NOTIFICATION_PLAY_SESSION_STATE]
        if not playSessionStates:
            return

        for playSessionState in playSessionStates:
            # TODO(Montellese)
            pass

    def _ProcessMessageActivity(self, data):
        if not WS_MESSAGE_NOTIFICATION_ACTIVITY in data:
            log('invalid activity message received from {}: {}'.format(mediaProvider2str(self._mediaProvider), json.dumps(data)), xbmc.LOGWARNING)
            return

        activities = data[WS_MESSAGE_NOTIFICATION_ACTIVITY]
        if not activities:
            return

        changedPlexItems = []
        for activity in activities:
            if not all(key in activity for key in (WS_MESSAGE_NOTIFICATION_ACTIVITY_EVENT, WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY)):
                continue
            # we are only interested in the final result
            if activity[WS_MESSAGE_NOTIFICATION_ACTIVITY_EVENT] != WS_MESSAGE_NOTIFICATION_ACTIVITY_EVENT_ENDED:
                continue

            activityDetails = activity[WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY]
            if not all(key in activityDetails for key in (WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_TYPE, WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_CONTEXT)):
                continue

            # we are only interested in changes to library items
            if activityDetails[WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_TYPE] != WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_TYPE_REFRESH_ITEMS:
                continue

            context = activityDetails[WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_CONTEXT]
            if not WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_CONTEXT_KEY in context:
                continue

            plexItemKey = context[WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_CONTEXT_KEY]
            plexItemId = Api.getItemIdFromPlexKey(plexItemKey)
            if not plexItemId:
                continue
            changedPlexItems.append((xbmcmediaimport.MediaImportChangesetTypeChanged, plexItemId, None))

        self._ProcessChangedPlexItems(changedPlexItems)

    def _ProcessChangedPlexItems(self, changedPlexItems):
        changedItems = []
        for (changesetType, plexItemId, plexItemClass) in changedPlexItems:
            item = None
            if changesetType == xbmcmediaimport.MediaImportChangesetTypeAdded or \
               changesetType == xbmcmediaimport.MediaImportChangesetTypeChanged:
                # get all details for the added / changed item
                item = self._GetItemDetails(plexItemId, plexItemClass)
                if not item:
                    log('failed to get details for changed item with id {}'.format(plexItemId), xbmc.LOGWARNING)
                    continue
            else:
                # find the removed item in the list of imported items
                importedItems = xbmcmediaimport.getImportedItemsByProvider(self._mediaProvider)
                matchingItems = [ importedItem for importedItem in importedItems if Api.getItemIdFromListItem(importedItem) == plexItemId ]
                if not matchingItems:
                    log('failed to find removed item with id {}'.format(plexItemId), xbmc.LOGWARNING)
                    continue
                if len(matchingItems) > 1:
                    log('multiple imported items for item with id {} found => only removing the first one'.format(plexItemId), xbmc.LOGWARNING)

                item = matchingItems[0]

            if not item:
                log('failed to process changed item with id {}'.format(plexItemId), xbmc.LOGWARNING)
                continue

            changedItems.append((changesetType, item, plexItemId))

        self._ChangeItems(changedItems)

    def _ChangeItems(self, changedItems):
         # map the changed items to their media import
        changedItemsMap = {}
        for (changesetType, item, plexItemId) in changedItems:
            if not item:
                continue

            # find a matching import for the changed item
            mediaImport = self._FindImportForItem(item)
            if not mediaImport:
                log('failed to determine media import for changed item with id {}'.format(plexItemId), xbmc.LOGWARNING)
                continue

            if mediaImport not in changedItemsMap:
                changedItemsMap[mediaImport] = []

            changedItemsMap[mediaImport].append((changesetType, item))

        # finally pass the changed items grouped by their media import to Kodi
        for (mediaImport, changedItems) in changedItemsMap.items():
            if xbmcmediaimport.changeImportedItems(mediaImport, changedItems):
                log('changed {} imported items for media import {}'.format(len(changedItems), mediaImport2str(mediaImport)))
            else:
                log('failed to change {} imported items for media import {}'.format(len(changedItems), mediaImport2str(mediaImport)), xbmc.LOGWARNING)

    def _GetItemDetails(self, plexItemId, plexItemClass=None):
        return Api.getPlexItemAsListItem(self._server.PlexServer(), plexItemId, plexItemClass)

    def _FindImportForItem(self, item):
        videoInfoTag = item.getVideoInfoTag()
        if not videoInfoTag:
            return None

        itemMediaType = videoInfoTag.getMediaType()

        matchingImports = [ mediaImport for mediaImport in self._imports if itemMediaType in mediaImport.getMediaTypes() ]
        if not matchingImports:
            return None

        return matchingImports[0]

    def _StartAction(self, mediaProvider):
        if not mediaProvider:
            raise RuntimeError('invalid mediaProvider')

        # if we are already connected check if something important changed in the media provider
        if self._connected:
            if Api.compareMediaProviders(self._mediaProvider, mediaProvider):
                return True

        self._StopAction(restart=True)

        self._mediaProvider = mediaProvider

        settings = self._mediaProvider.prepareSettings()
        if not settings:
            raise RuntimeError('cannot prepare media provider settings')

        # create Plex server instance
        self._server = Server(self._mediaProvider)

        # first authenticate with the Plex Media Server
        try:
            authenticated = self._server.Authenticate()
        except:
            authenticated = False

        if not authenticated:
            log('failed to authenticate with {}'.format(mediaProvider2str(self._mediaProvider)), xbmc.LOGERROR)
            self._Reset()
            return False

        # prepare the URL
        url = self._server.PlexServer().url(self.ENDPOINT, includeToken=True).replace('http', 'ws')

        # connect the websocket
        try:
            self._websocket.connect(url)
        except:
            log('failed to connect to {} using a websocket'.format(url), xbmc.LOGERROR)
            self._Reset()
            return False

        log('successfully connected to {} to observe media imports'.format(mediaProvider2str(self._mediaProvider)))
        self._connected = True
        return True

    def _StopAction(self, restart=False):
        if not self._connected:
            return

        self._websocket.close()
        self._Reset()

        if not restart:
            log('stopped observing media imports from {}'.format(mediaProvider2str(self._mediaProvider)))

    def _Reset(self):
        self._connected = False
        self._server = None
        self._mediaProvider = None
