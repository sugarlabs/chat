# Copyright 2007 Collabora Ltd.
# Copyright 2007 One Laptop Per Child
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

from gettext import gettext as _

import gtk
import gobject
import hippo
from sugar.graphics.alert import Alert, _TimeoutIcon
from sugar.graphics import style

class NotifyAlert(Alert):
    """Timeout alert with only an "OK" button - just for notifications"""

    def __init__(self, timeout=5, **kwargs):
        Alert.__init__(self, **kwargs)

        self._timeout = timeout

        self._timeout_text = _TimeoutIcon(
            text=self._timeout,
            color=style.COLOR_BUTTON_GREY.get_int(),
            background_color=style.COLOR_WHITE.get_int())
        canvas = hippo.Canvas()
        canvas.set_root(self._timeout_text)
        canvas.show()
        self.add_button(gtk.RESPONSE_OK, _('OK'), canvas)

        gobject.timeout_add(1000, self.__timeout)

    def __timeout(self):
        self._timeout -= 1
        self._timeout_text.props.text = self._timeout
        if self._timeout == 0:
            self._response(gtk.RESPONSE_OK)
            return False
        return True
