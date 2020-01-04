#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import sys
import plex
from lib import importer
from lib.utils import log


if __name__ == '__main__':
    # initialize some global variables
    plex.Initialize()

    log('Plex Media Import importer started')
    importer.run(sys.argv)
