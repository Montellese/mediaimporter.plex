#!/usr/bin/python
# -*- coding: utf-8 -*-/*
#  Copyright (C) 2021 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import logging
from queue import Empty, Queue
from time import sleep
from typing import List

from xbmc import LOGWARNING  # pylint: disable=import-error
from xbmcgui import ListItem  # pylint: disable=import-error
from xbmcmediaimport import MediaImport, MediaProvider  # pylint: disable=import-error

from plexapi.base import PlexPartialObject
from plexapi.server import PlexServer
from plexapi.video import Video

from lib.background_thread import BackgroundThread
from lib.settings import ImportSettings
from lib.utils import log, mediaProvider2str
from plex.api import Api

class ToFileItemConverterThread(BackgroundThread):
    INCLUDES = {
        # the following includes are explicitely set
        'includeExtras': True,
        'includeMarkers': True,
        'checkFiles': False,
        'skipRefresh': True,
        # the following includes are disabled to minimize the result
        'includeAllConcerts': False,
        'includeBandwidths': False,
        'includeChapters': False,
        'includeChildren': False,
        'includeConcerts': False,
        'includeExternalMedia': False,
        'includeGeolocation': False,
        'includeLoudnessRamps': False,
        'includeOnDeck': False,
        'includePopularLeaves': False,
        'includePreferences': False,
        'includeRelated': False,
        'includeRelatedCount': False,
        'includeReviews': False,
        'includeStations': False,
    }

    def __init__(self,
            media_provider: MediaProvider,
            media_import: MediaImport,
            plex_server: PlexServer,
            media_type: str = "",
            plex_lib_type: str = "",
            allow_direct_play: bool = False):

        self._media_provider = media_provider
        self._media_import = media_import
        self._plex_server = plex_server
        self._media_type = media_type
        self._plex_lib_type = plex_lib_type
        self._allow_direct_play = allow_direct_play

        self._items_to_process_queue = Queue()
        self._processed_items_queue = Queue()

        self._count_items_to_process = 0
        self._count_processed_items = 0

        super(ToFileItemConverterThread, self).__init__(name="ToFileItemConverterThread")

    def add_items_to_convert(self, plex_items: List[Video]):
        if not plex_items:
            raise ValueError("invalid plex_items")

        if self.should_stop():
            return

        for plex_item in plex_items:
            self._items_to_process_queue.put(plex_item)

        self._count_items_to_process += len(plex_items)

    def get_converted_items(self) -> List[ListItem]:
        converted_items = []
        while not self._processed_items_queue.empty():
            try:
                converted_items.append(self._processed_items_queue.get_nowait())
                self._processed_items_queue.task_done()
            except Empty:
                break

        return converted_items

    def get_items_to_convert_count(self) -> int:
        return self._count_items_to_process

    def get_converted_items_count(self) -> int:
        return self._count_processed_items

    def run(self):
        numRetriesOnTimeout = ImportSettings.GetNumberOfRetriesOnTimeout(self._media_import)
        numSecondsBetweenRetries = ImportSettings.GetNumberOfSecondsBetweenRetries(self._media_import)

        while not self.should_stop():
            while not self.should_stop():
                plex_item = None
                try:
                    plex_item = self._items_to_process_queue.get_nowait()
                except Empty:
                    # if the queue is empty and we should finish, return completely
                    if self.should_finish():
                        return
                    break

                converted_item = None

                retries = numRetriesOnTimeout
                while retries > 0:
                    try:
                        # manually reload the item's metadata
                        if isinstance(plex_item, PlexPartialObject) and not plex_item.isFullObject():
                            plex_item.reload(**ToFileItemConverterThread.INCLUDES)

                        # convert the plex item to a ListItem
                        converted_item = Api.toFileItem(
                            self._plex_server, plex_item, mediaType=self._media_type,
                            plexLibType=self._plex_lib_type, allowDirectPlay=self._allow_direct_play)

                        # get out of the retry loop
                        break
                    except Exception as e:
                        # Api.convertDateTimeToDbDateTime may return (404) not_found for orphaned items in the library
                        log(
                            (
                                f"failed to retrieve item {plex_item.title} with key {plex_item.key} "
                                f"from {mediaProvider2str(self._media_provider)}: {e}"
                            ),
                            LOGWARNING)

                        # retry after timeout
                        retries -= 1

                        # check if there are any more retries left
                        # if not skip the item
                        if retries == 0:
                            log(
                                (
                                    f"retrieving item {plex_item.title} with key {plex_item.key} from "
                                    f"{mediaProvider2str(self._media_provider)} failed after "
                                    f"{numRetriesOnTimeout} retries"
                                ),
                                LOGWARNING)
                        else:
                            # otherwise wait before trying again
                            log(
                                (
                                    f"retrying to retrieve {plex_item.title} with key {plex_item.key} from "
                                    f"{mediaProvider2str(self._media_provider)} in "
                                    f"{numSecondsBetweenRetries} seconds"
                                )
                            )
                            sleep(float(numSecondsBetweenRetries))

                # let the input queue know that the plex item has been processed
                self._items_to_process_queue.task_done()

                if converted_item:
                    # put the converted item into the output queue
                    self._processed_items_queue.put(converted_item)
                else:
                    log(
                        (
                            f"failed to convert item {plex_item.title} with key {plex_item.key} "
                            f"from {mediaProvider2str(self._media_provider)}"
                        ),
                        LOGWARNING)

                self._count_items_to_process -= 1
                self._count_processed_items += 1

            # wait for the stop event
            self._stop_event.wait(0.1)