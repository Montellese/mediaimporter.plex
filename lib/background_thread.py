#!/usr/bin/python
# -*- coding: utf-8 -*-/*
#  Copyright (C) 2021 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from threading import Event, Thread

class BackgroundThread(Thread):
    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}):
        self._finish_flag = False
        self._stop_flag = False
        self._stop_event = Event()

        super(BackgroundThread, self).__init__(group, target, name, args, kwargs)

    def __del__(self):
        self.stop()
    
    def finish(self):
        if self.should_finish() or self.should_stop():
            return

        self._finish_flag = True
        self.stop(True)

    def should_finish(self):
        return self._finish_flag

    def stop(self, wait: bool = False, waitTimeout=None):
        if not self.should_stop():
            self._stop_flag = True
            self._stop_event.set()
        
        if wait:
            self.join(waitTimeout)

    def should_stop(self):
        return self._stop_flag
