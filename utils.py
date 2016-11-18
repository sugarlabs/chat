#
#   utils.py, Copyright (C) 2014-2016 One Laptop per Child
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 2 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License along
#   with this program; if not, write to the Free Software Foundation, Inc.,
#   51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import subprocess

from gi.repository import GObject


class EbookModeDetector(GObject.GObject):

    DEVICE = '/dev/input/event4'

    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, ([bool])), }

    def __init__(self):
        GObject.GObject.__init__(self)

        try:
            self._fp = open(self.DEVICE, 'rb')
        except IOError:
            self._ebook_mode = False
            return

        def _io_in_cb(fp, condition):
            data = fp.read(16)
            if data == '':
                return False
            if ord(data[10]) == 1:  # SW_TABLET_MODE
                mode = (ord(data[12]) == 1)
                if mode != self._ebook_mode:
                    self._ebook_mode = mode
                    self.emit('changed', self._ebook_mode)
            return True

        self._sid = GObject.io_add_watch(self._fp, GObject.IO_IN, _io_in_cb)

        self._ebook_mode = self._get_initial_value()

    def get_ebook_mode(self):
        return self._ebook_mode

    def _get_initial_value(self):
        try:
            output = subprocess.call(['evtest', '--query', self.DEVICE,
                                      'EV_SW', 'SW_TABLET_MODE'])
            # 10 is ebook_mode, 0 is normal
            return (output == 10)
        except:
            return False
