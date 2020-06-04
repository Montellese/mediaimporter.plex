#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import json
from typing import List
import websocket

import plexapi
import xbmc  # pylint: disable=import-error
import xbmcgui  # pylint: disable=import-error
import xbmcmediaimport  # pylint: disable=import-error

import plex.api as api
import plex.constants as constants
from plex.server import Server

from lib.utils import log, mediaImport2str, mediaProvider2str


class ProviderObserver:
    """Class for observing the PMS websocket stream for live updates and processing the messages."""
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
        self._websocket = websocket.WebSocket()
        self._websocket.settimeout(0.1)

    def __del__(self):
        self._StopAction()

    def AddImport(self, mediaImport: xbmcmediaimport.MediaImport):
        """Add, or update if existing, mediaImport into list of imports

        :param mediaImport: mediaImport object to update into the import list
        :type mediaImport: :class:`xbmcmediaimport.MediaImport`
        """
        if not mediaImport:
            raise ValueError('invalid mediaImport')

        # look for a matching import
        matchingImportIndices = self._FindImportIndices(mediaImport)
        # if a matching import has been found update it
        if matchingImportIndices:
            self._imports[matchingImportIndices[0]] = mediaImport
            log(f"media import {mediaImport2str(mediaImport)} updated", xbmc.LOGINFO)
        else:
            # other add the import to the list
            self._imports.append(mediaImport)
            log(f"media import {mediaImport2str(mediaImport)} added", xbmc.LOGINFO)

    def RemoveImport(self, mediaImport: xbmcmediaimport.MediaImport):
        """Remove an existing mediaImport from the list of imports

        :param mediaImport: mediaImport object to remove from the import plist
        :type mediaImport: :class:`xbmcmediaimport.MediaImport`
        """
        if not mediaImport:
            raise ValueError('invalid mediaImport')

        # look for a matching import
        matchingImportIndices = self._FindImportIndices(mediaImport)
        if not matchingImportIndices:
            return

        # remove the media import from the list
        del self._imports[matchingImportIndices[0]]
        log(f"media import {mediaImport2str(mediaImport)} removed", xbmc.LOGINFO)

    def Start(self, mediaProvider: xbmcmediaimport.MediaProvider):
        """Trigger start of observation for the provided mediaProvider

        :param mediaProvider: Media provider to start observing
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        """
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        self._actions.append((ProviderObserver.Action.Start, mediaProvider))

    def Stop(self):
        """End all observation tasks"""
        self._actions.append((ProviderObserver.Action.Stop, None))

    def Process(self):
        """Main trigger to process all queued messages and provider actions"""
        # process any open actions
        self._ProcessActions()
        # process any incoming messages
        self._ProcessMessages()

    def _FindImportIndices(self, mediaImport: xbmcmediaimport.MediaImport) -> List[int]:
        """Find the list index for the provided mediaImport object in the imports list if present

        :param mediaImport: The mediaImport object to find in the imports list
        :type mediaImport: :class:`xbmcmediaimport.MediaImport`
        :return: List of indexes where the mediaImport object was found
        :rtype: list
        """
        if not mediaImport:
            raise ValueError('invalid mediaImport')

        return [
            i for i, x in enumerate(self._imports)
            if x.getPath() == mediaImport.getPath() and x.getMediaTypes() == mediaImport.getMediaTypes()
        ]

    def _ProcessActions(self):
        """Process pending provider actions in the queue (start/stop observation)"""
        for (action, data) in self._actions:
            if action == ProviderObserver.Action.Start:
                self._StartAction(data)
            elif action == ProviderObserver.Action.Stop:
                self._StopAction()
            else:
                log(f"unknown action {action} to process", xbmc.LOGWARNING)

        self._actions = []

    def _ProcessMessages(self):
        """Trigger processing of messages from the media providers websocket"""
        # nothing to do if we are not connected to a Plex server
        if not self._connected:
            return

        while True:
            try:
                message = self._websocket.recv()
                if message is None:
                    break

                messageObj = json.loads(message)
                if not messageObj:
                    log(
                        (
                            f"invalid JSON message ({len(message)}) from {mediaProvider2str(self._mediaProvider)} "
                            f"received: {message}"
                        ),
                        xbmc.LOGWARNING
                    )
                    continue

                self._ProcessMessage(messageObj)

            except websocket.WebSocketTimeoutException:
                break
            except Exception as e:
                log(
                    f"unknown exception when receiving data from {mediaProvider2str(self._mediaProvider)}: "
                    f"{e.args[0]}",
                    xbmc.LOGWARNING
                )
                break

    def _ProcessMessage(self, message: dict):
        """Determine message type and pass to appropriate processing function

        :param message: Message data to be processed
        :type message: dict
        """
        if not message:
            return

        if constants.WS_MESSAGE_NOTIFICATION_CONTAINER not in message:
            log(
                (
                    f"message without '{constants.WS_MESSAGE_NOTIFICATION_CONTAINER}'"
                    f"received from {mediaProvider2str(self._mediaProvider)}: {json.dumps(message)}"
                ),
                xbmc.LOGWARNING
            )
            return

        messageData = message[constants.WS_MESSAGE_NOTIFICATION_CONTAINER]
        if constants.WS_MESSAGE_NOTIFICATION_TYPE not in messageData:
            log(
                (
                    f"message without '{constants.WS_MESSAGE_NOTIFICATION_TYPE}'"
                    f"received from {mediaProvider2str(self._mediaProvider)}: {json.dumps(message)}"
                ),
                xbmc.LOGWARNING
            )
            return

        messageType = messageData[constants.WS_MESSAGE_NOTIFICATION_TYPE]
        if messageType == constants.WS_MESSAGE_NOTIFICATION_TYPE_TIMELINE:
            self._ProcessMessageTimelineEntry(messageData)
        elif messageType == constants.WS_MESSAGE_NOTIFICATION_TYPE_PLAYING:
            self._ProcessMessagePlaySessionState(messageData)
        elif messageType == constants.WS_MESSAGE_NOTIFICATION_TYPE_ACTIVITY:
            self._ProcessMessageActivity(messageData)
        else:
            log(
                f"ignoring '{messageType}' from {mediaProvider2str(self._mediaProvider)}: {json.dumps(message)}",
                xbmc.LOGWARNING
            )

    def _ProcessMessageTimelineEntry(self, data: dict):
        """Gather details from a Timeline Entry message, format into a plex change and trigger further processing

        :param data: Timeline message data to process
        :type data: dict
        """
        if constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY not in data:
            log(
                f"invalid timeline message received from {mediaProvider2str(self._mediaProvider)}: {json.dumps(data)}",
                xbmc.LOGWARNING
            )
            return

        timelineEntries = data[constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY]
        if not timelineEntries:
            return

        required_keys = (
            constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_IDENTIFIER,
            constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_ITEM_ID,
            constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE,
            constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_STATE
        )

        changedPlexItems = []
        for timelineEntry in timelineEntries:
            if not all(key in timelineEntry for key in required_keys):
                continue

            # we are only interested in library changes
            if (
                    timelineEntry[constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_IDENTIFIER]
                    != constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_IDENTIFIER_LIBRARY
            ):
                continue

            plexItemId = int(timelineEntry[constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_ITEM_ID])
            if not plexItemId:
                continue

            # filter and determine the changed item's library type / class
            plexItemType = timelineEntry[constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE]
            if plexItemType == constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE_MOVIE:
                plexItemLibraryType = api.PLEX_LIBRARY_TYPE_MOVIE
            elif plexItemType == constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE_TVSHOW:
                plexItemLibraryType = api.PLEX_LIBRARY_TYPE_TVSHOW
            elif plexItemType == constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE_SEASON:
                plexItemLibraryType = api.PLEX_LIBRARY_TYPE_SEASON
            elif plexItemType == constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_TYPE_EPISODE:
                plexItemLibraryType = api.PLEX_LIBRARY_TYPE_EPISODE
            else:
                continue

            plexItemMediaClass = api.Api.getPlexMediaClassFromLibraryType(plexItemLibraryType)

            # filter and process the changed item's state
            plexItemState = timelineEntry[constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_STATE]
            if plexItemState == constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_STATE_CREATED:
                plexItemChangesetType = xbmcmediaimport.MediaImportChangesetTypeAdded
            elif plexItemState == constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_STATE_FINISHED:
                plexItemChangesetType = xbmcmediaimport.MediaImportChangesetTypeChanged
            elif plexItemState == constants.WS_MESSAGE_NOTIFICATION_TIMELINE_ENTRY_STATE_DELETED:
                plexItemChangesetType = xbmcmediaimport.MediaImportChangesetTypeRemoved
            else:
                continue

            changedPlexItems.append((plexItemChangesetType, plexItemId, plexItemMediaClass))

        self._ProcessChangedPlexItems(changedPlexItems)

    def _ProcessMessagePlaySessionState(self, data: dict):
        """
        Gather details from a Play Session message, format into a plex change and trigger further processing
        Not Implemented

        :param data: Play Session message data to process
        :type data: dict
        """
        if constants.WS_MESSAGE_NOTIFICATION_PLAY_SESSION_STATE not in data:
            log(
                f"invalid playing message received from {mediaProvider2str(self._mediaProvider)}: {json.dumps(data)}",
                xbmc.LOGWARNING
            )
            return

        playSessionStates = data[constants.WS_MESSAGE_NOTIFICATION_PLAY_SESSION_STATE]
        if not playSessionStates:
            return

        # TODO(Montellese)
        # for playSessionState in playSessionStates:
        #     pass

    def _ProcessMessageActivity(self, data: dict):
        """Gather details from an Activity message, format into a plex change and trigger further processing

        :param data: Activity message data to process
        :type data: dict
        """
        if constants.WS_MESSAGE_NOTIFICATION_ACTIVITY not in data:
            log(
                f"invalid activity message received from {mediaProvider2str(self._mediaProvider)}: {json.dumps(data)}",
                xbmc.LOGWARNING
            )
            return

        activities = data[constants.WS_MESSAGE_NOTIFICATION_ACTIVITY]
        if not activities:
            return

        required_activity_keys = (
            constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_EVENT,
            constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY
        )
        required_activity_details_keys = (
            constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_TYPE,
            constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_CONTEXT
        )

        changedPlexItems = []
        for activity in activities:
            if not all(key in activity for key in required_activity_keys):
                continue
            # we are only interested in the final result
            if (
                    activity[constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_EVENT]
                    != constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_EVENT_ENDED
            ):
                continue

            activityDetails = activity[constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY]
            if not all(key in activityDetails for key in required_activity_details_keys):
                continue

            # we are only interested in changes to library items
            if (
                    activityDetails[constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_TYPE]
                    != constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_TYPE_REFRESH_ITEMS
            ):
                continue

            context = activityDetails[constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_CONTEXT]
            if constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_CONTEXT_KEY not in context:
                continue

            plexItemKey = context[constants.WS_MESSAGE_NOTIFICATION_ACTIVITY_ACTIVITY_CONTEXT_KEY]
            plexItemId = api.Api.getItemIdFromPlexKey(plexItemKey)
            if not plexItemId:
                continue

            changedPlexItems.append((xbmcmediaimport.MediaImportChangesetTypeChanged, plexItemId, None))

        self._ProcessChangedPlexItems(changedPlexItems)

    def _ProcessChangedPlexItems(self, changedPlexItems: List[tuple]):
        """
        Determine if change was an add/update or remove operation,
        pull the details of the item being changed,
        format and trigger further processing

        :param changedPlexItems: List of plex change tuples parsed from websocket messages to process
        :type changedPlexItems: list
        """
        changedItems = []
        for (changesetType, plexItemId, plexItemClass) in changedPlexItems:
            item = None
            if changesetType in (
                    xbmcmediaimport.MediaImportChangesetTypeAdded,
                    xbmcmediaimport.MediaImportChangesetTypeChanged
            ):
                # get all details for the added / changed item
                item = self._GetItemDetails(plexItemId, plexItemClass)
                if not item:
                    log(f"failed to get details for changed item with id {plexItemId}", xbmc.LOGWARNING)
                    continue
            else:
                # find the removed item in the list of imported items
                importedItems = xbmcmediaimport.getImportedItemsByProvider(self._mediaProvider)
                matchingItems = [
                    importedItem for importedItem in importedItems
                    if api.Api.getItemIdFromListItem(importedItem) == plexItemId
                ]
                if not matchingItems:
                    log(f"failed to find removed item with id {plexItemId}", xbmc.LOGWARNING)
                    continue
                if len(matchingItems) > 1:
                    log(
                        f"multiple imported items for item with id {plexItemId} found => only removing the first one",
                        xbmc.LOGWARNING
                    )

                item = matchingItems[0]

            if not item:
                log(f"failed to process changed item with id {plexItemId}", xbmc.LOGWARNING)
                continue

            changedItems.append((changesetType, item, plexItemId))

        self._ChangeItems(changedItems)

    def _ChangeItems(self, changedItems: List[tuple]):
        """Send change details to Kodi to perform library updates

        :param changedItems: List of change detail tuples to process
        :type changedItems: list
        """
        # map the changed items to their media import
        changedItemsMap = {}
        for (changesetType, item, plexItemId) in changedItems:
            if not item:
                continue

            # find a matching import for the changed item
            mediaImport = self._FindImportForItem(item)
            if not mediaImport:
                log(f"failed to determine media import for changed item with id {plexItemId}", xbmc.LOGWARNING)
                continue

            if mediaImport not in changedItemsMap:
                changedItemsMap[mediaImport] = []

            changedItemsMap[mediaImport].append((changesetType, item))

        # finally pass the changed items grouped by their media import to Kodi
        for (mediaImport, itemsByImport) in changedItemsMap.items():
            if xbmcmediaimport.changeImportedItems(mediaImport, itemsByImport):
                log(
                    f"changed {len(itemsByImport)} imported items for media import {mediaImport2str(mediaImport)}",
                    xbmc.LOGINFO
                )
            else:
                log(
                    (
                        f"failed to change {len(itemsByImport)} imported items "
                        f"for media import {mediaImport2str(mediaImport)}"
                    ),
                    xbmc.LOGWARNING
                )

    def _GetItemDetails(self, plexItemId: int, plexItemClass: plexapi.video.Video = None) -> xbmcgui.ListItem:
        """Pull details of plex item from the PMS server as a kodi ListItem

        :param plexItemId: ID of the item in PMS to get the details of
        :type plexItemId: int
        :param plexItemClass: Plex video object media type
        :type plexItemClass: :class:`plexapi.video.Video`, optional
        :return: ListItem object populated with the details of the plex item
        :rtype: :class:`xbmc.ListItem`
        """
        return api.Api.getPlexItemAsListItem(self._server.PlexServer(), plexItemId, plexItemClass)

    def _FindImportForItem(self, item: xbmcgui.ListItem) -> xbmcmediaimport.MediaImport:
        """Find a matching MediaImport in the imports list for the provided ListItem

        :param item: The plex import item in ListItem object to find a matching import for
        :type item: :class:`xbmcgui.ListItem`
        :return: The matching MediaImport item if found
        :rtype: :class:`xbmcmediaimport.MediaImport`
        """
        videoInfoTag = item.getVideoInfoTag()
        if not videoInfoTag:
            return None

        itemMediaType = videoInfoTag.getMediaType()

        matchingImports = [mediaImport for mediaImport in self._imports if itemMediaType in mediaImport.getMediaTypes()]
        if not matchingImports:
            return None

        return matchingImports[0]

    def _StartAction(self, mediaProvider: xbmcmediaimport.MediaProvider) -> bool:
        """Establish websocket connection to the provided MediaProvder and begin listening

        :param mediaProvider: MediaProvider with websocket to connect to
        :type mediaProvider: :class:`xbmcmediaimport.MediaProvider`
        :return: Whether the connection was successful or not
        :rtype: bool
        """
        if not mediaProvider:
            raise RuntimeError('invalid mediaProvider')

        # if we are already connected check if something important changed in the media provider
        if self._connected:
            if api.Api.compareMediaProviders(self._mediaProvider, mediaProvider):
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
            log(f"failed to authenticate with {mediaProvider2str(self._mediaProvider)}", xbmc.LOGERROR)
            self._Reset()
            return False

        # prepare the URL
        url = self._server.PlexServer().url(self.ENDPOINT, includeToken=True).replace('http', 'ws')

        # connect the websocket
        try:
            self._websocket.connect(url)
        except:
            log(f"failed to connect to {url} using a websocket", xbmc.LOGERROR)
            self._Reset()
            return False

        log(
            f"successfully connected to {mediaProvider2str(self._mediaProvider)} to observe media imports",
            xbmc.LOGINFO
        )
        self._connected = True
        return True

    def _StopAction(self, restart: bool = False):
        """Close the current websocket connection and reset connection details back to defaults

        :param restart: Whether the connection should be re-started or not
        :type restart: bool, optional
        """
        if not self._connected:
            return

        if not restart:
            log(f"stopped observing media imports from {mediaProvider2str(self._mediaProvider)}", xbmc.LOGINFO)

        self._websocket.close()
        self._Reset()

    def _Reset(self):
        """Reset connection state variables back to defaults"""
        self._connected = False
        self._server = None
        self._mediaProvider = None
