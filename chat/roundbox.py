# Copyright 2014, Sugar Labs
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

import math
from gi.repository import Gtk
from gi.repository import GObject
from sugar3.graphics import style

BORDER_DEFAULT = style.LINE_WIDTH


class RoundBox(Gtk.HBox):
    __gtype_name__ = 'RoundBox'

    def __init__(self, **kwargs):
        GObject.GObject.__init__(self, **kwargs)
        self._radius = style.zoom(10)
        self.border_color = style.COLOR_BLACK
        self.background_color = None
        self.set_resize_mode(Gtk.ResizeMode.PARENT)
        self.connect('draw', self.__expose_cb)
        self.connect('add', self.__add_cb)

    def __add_cb(self, child, params):
        child.set_border_width(style.zoom(5))

    def __expose_cb(self, widget, cr):
        rect = self.get_allocation()
        x = rect.x
        y = rect.y
        width = rect.width - BORDER_DEFAULT
        height = rect.height - BORDER_DEFAULT

        cr.move_to(x, y)
        cr.arc(x + width - self._radius, y + self._radius,
               self._radius, math.pi * 1.5, math.pi * 2)
        cr.arc(x + width - self._radius, y + height - self._radius,
               self._radius, 0, math.pi * 0.5)
        cr.arc(x + self._radius, y + height - self._radius,
               self._radius, math.pi * 0.5, math.pi)
        cr.arc(x + self._radius, y + self._radius, self._radius,
               math.pi, math.pi * 1.5)
        cr.close_path()

        if self.background_color is not None:
            r, g, b, __ = self.background_color.get_rgba()
            cr.set_source_rgb(r, g, b)
            cr.fill_preserve()

        if self.border_color is not None:
            r, g, b, __ = self.border_color.get_rgba()
            cr.set_source_rgb(r, g, b)
            cr.set_line_width(BORDER_DEFAULT)
            cr.stroke()
        return False
