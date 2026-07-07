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
from gi.repository import Graphene
from gi.repository import Gsk

from sugar4.graphics import style

_BORDER_DEFAULT = style.LINE_WIDTH

_SHARED_PROVIDER = None


class RoundBox(Gtk.Box):
    __gtype_name__ = 'RoundBox'

    def __init__(self, **kwargs):
        kwargs.setdefault('orientation', Gtk.Orientation.HORIZONTAL)
        Gtk.Box.__init__(self, **kwargs)
        
        self.add_css_class('roundbox')
        self.connect('realize', self._on_realize)
        
        self._radius = style.zoom(15)
        self._border_color = style.COLOR_BLACK
        self._tail = None
        self._background_color = None

    def _on_realize(self, widget):
        widget.disconnect_by_func(self._on_realize)
        
        global _SHARED_PROVIDER
        if _SHARED_PROVIDER is None:
            _SHARED_PROVIDER = Gtk.CssProvider()
            _SHARED_PROVIDER.load_from_string('.roundbox { background: none; border: none; }')
            Gtk.StyleContext.add_provider_for_display(
                self.get_display(),
                _SHARED_PROVIDER,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    @property
    def border_color(self): return self._border_color
    @border_color.setter
    def border_color(self, v): self._border_color = v; self.queue_draw()

    @property
    def background_color(self): return self._background_color
    @background_color.setter
    def background_color(self, v): self._background_color = v; self.queue_draw()

    @property
    def tail(self): return self._tail
    @tail.setter
    def tail(self, v): self._tail = v; self.queue_draw()

    def append(self, child):
        # Replicate GTK3 __add_cb border padding
        padding = style.zoom(5)
        child.set_margin_start(child.get_margin_start() + padding)
        child.set_margin_end(child.get_margin_end() + padding)
        child.set_margin_top(child.get_margin_top() + padding)
        child.set_margin_bottom(child.get_margin_bottom() + padding)
        super().append(child)

    def pack_start(self, child, expand, fill, padding):
        '''GTK3 compat wrapper — just delegates to append.'''
        self.append(child)

    def add(self, child):
        '''GTK3 compat wrapper — just delegates to append.'''
        self.append(child)

    def do_snapshot(self, snapshot):
        w = self.get_width()
        h = self.get_height()
        if w <= 0 or h <= 0:
            return
            
        rect = Graphene.Rect()
        rect.init(0, 0, w, h)
        cr = snapshot.append_cairo(rect)

        hmargin = style.zoom(15)
        x = hmargin
        y = 0
        width = w - _BORDER_DEFAULT * 2. - hmargin * 2
        if self.tail is None:
            height = h - _BORDER_DEFAULT * 2.
        else:
            height = h - _BORDER_DEFAULT * 2. - self._radius

        cr.move_to(x + self._radius, y)
        cr.arc(x + width - self._radius, y + self._radius,
               self._radius, math.pi * 1.5, math.pi * 2)
        tail_height = style.zoom(5)
        if self.tail == 'right':
            cr.arc(x + width - self._radius, y + height - self._radius * 2,
                   self._radius, 0, math.pi * 0.5)
            cr.line_to(x + width - self._radius, y + height)
            cr.line_to(x + width - tail_height * self._radius,
                       y + height - self._radius)
            cr.arc(x + self._radius, y + height - self._radius * 2,
                   self._radius, math.pi * 0.5, math.pi)
        elif self.tail == 'left':
            cr.arc(x + width - self._radius, y + height - self._radius * 2,
                   self._radius, 0, math.pi * 0.5)
            cr.line_to(x + self._radius * tail_height,
                       y + height - self._radius)
            cr.line_to(x + self._radius, y + height)
            cr.line_to(x + self._radius, y + height - self._radius)
            cr.arc(x + self._radius, y + height - self._radius * 2,
                   self._radius, math.pi * 0.5, math.pi)
        else:
            cr.arc(x + width - self._radius, y + height - self._radius,
                   self._radius, 0, math.pi * 0.5)
            cr.arc(x + self._radius, y + height - self._radius,
                   self._radius, math.pi * 0.5, math.pi)
        cr.arc(x + self._radius, y + self._radius, self._radius,
               math.pi, math.pi * 1.5)
        cr.close_path()

        if self._background_color is not None:
            r, g, b, a = self._background_color.get_rgba()
            cr.set_source_rgba(r, g, b, a)
            cr.fill_preserve()

        if self._border_color is not None:
            r, g, b, a = self._border_color.get_rgba()
            cr.set_source_rgba(r, g, b, a)
            cr.set_line_width(_BORDER_DEFAULT)
            cr.stroke()

        # Render children on top of the background
        Gtk.Box.do_snapshot(self, snapshot)
