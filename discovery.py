#!/usr/bin/python
# -*- coding: utf-8 -*-/*
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import plex
from lib.discovery import DiscoveryService
from lib.utils import log


if __name__ == '__main__':
    # initialize some global variables
    plex.Initialize()

    # instantiate and start the discovery service
    log('Plex Media Server discoverer started')
    DiscoveryService()
