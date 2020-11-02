#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2021 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from xbmcgui import (  # pylint: disable=import-error
    ACTION_NAV_BACK,
    ACTION_PREVIOUS_MENU,
    ACTION_STOP,
    WindowXMLDialog
)

from lib.utils import getAddonPath, log

class SkipIntroDialog(WindowXMLDialog):
    CONTROL_ID_SKIP_INTRO = 3002  # TODO(Montellese)

    @staticmethod
    def Create():
        return SkipIntroDialog(
            "DialogSkipIntro.xml",
            getAddonPath(),
            "default",
            "720p"
            )

    def __init__(self, *args, **kwargs):
        super(WindowXMLDialog, self).__init__(*args, **kwargs)

        self._isOpen = False
        self._skipConfirmed = False

    def show(self):
        if not self.isOpen():
            log('showing skip intro dialog')
            self._isOpen = True
            self._skipConfirmed = False
            WindowXMLDialog.show(self)

    def close(self):
        if self.isOpen():
            log('closing skip intro dialog')
            self._isOpen = False
            WindowXMLDialog.close(self)

    def onClick(self, controlId):  # pylint: disable=invalid-name
        if controlId == SkipIntroDialog.CONTROL_ID_SKIP_INTRO:
            log('skipping intro activated')
            self._skipConfirmed = True
            self.close()

    def onAction(self, action):  # pylint: disable=invalid-name
        if action in (ACTION_PREVIOUS_MENU, ACTION_STOP, ACTION_NAV_BACK):
            self._skipConfirmed = False
            self.close()

    def isOpen(self) -> bool:
        return self._isOpen

    def skipIntro(self) -> bool:
        return self._skipConfirmed
