# Copyright 2007 Collabora Ltd.
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

import dbus
import hippo
import gtk
import pango
import logging
from datetime import datetime

from sugar import profile
from sugar.activity.activity import Activity
from sugar.graphics import font
from sugar.graphics.canvasicon import CanvasIcon
from sugar.graphics.roundbox import RoundBox
from sugar.graphics.xocolor import XoColor
from sugar.graphics.units import points_to_pixels as px
from sugar.presence import presenceservice

from telepathy.client import Connection, Channel

from telepathy.interfaces import (
    CONN_INTERFACE, PROPERTIES_INTERFACE,
    CHANNEL_INTERFACE_GROUP, CONN_INTERFACE_ALIASING,
    CHANNEL_TYPE_TEXT)

CONN_INTERFACE_BUDDY_INFO = 'org.laptop.Telepathy.BuddyInfo'

from telepathy.constants import (
    CONNECTION_HANDLE_TYPE_NONE, CONNECTION_HANDLE_TYPE_CONTACT,
    CONNECTION_HANDLE_TYPE_ROOM, CHANNEL_TEXT_MESSAGE_TYPE_NORMAL,
    CONNECTION_STATUS_CONNECTED, CONNECTION_STATUS_DISCONNECTED,
    CONNECTION_STATUS_CONNECTING)

room = 'chat@conference.olpc.collabora.co.uk'

logger = logging.getLogger('chat-activity')

class Chat(Activity):
    def __init__(self, handle):
        Activity.__init__(self, handle)

        self.set_title('Chat')

        root = self.make_root()
        self.set_canvas(root)
        root.show_all()

        self.owner_color = profile.get_color()
        self.owner_nickname = profile.get_nick_name()

        # for chat logging, we want to save the log as text/plain
        # in the Journal so it will resume with the appropriate
        # activity to view the chat log.
        # XXX MorganCollett 2007/06/19: change to text/html once the
        #     browser is verified to handle that mime type
        self._chat_log = ''
        self.metadata['activity'] = ''
        self.metadata['mime_type'] = 'text/plain'

        #self.add_text(self.owner_nickname, self.make_owner_icon(), 'Hello')
        # test long line
        #self.add_text(self.owner_nickname, self.make_owner_icon(),
        #    'one two three four five six seven eight nine ten ' +
        #    'one two three four five six seven eight nine ten ' +
        #    'one two three four five six seven eight nine ten ' +
        #    'one two three four five six seven eight nine ten')

        pservice = presenceservice.get_instance()

        bus = dbus.Bus()
        name, path = pservice.get_preferred_connection()
        conn = Connection(name, path)
        conn[CONN_INTERFACE].connect_to_signal('StatusChanged', self.status_changed_cb)

        self.conn = conn
        self.conn_name = name
        self.chan = None

        status = conn[CONN_INTERFACE].GetStatus()
        if status == CONNECTION_STATUS_CONNECTED:
            logger.debug("connected")
            self.join_room ()

    def received_cb(self, id, timestamp, sender, type, flags, text):
        try:
            # XXX: Shoule use PS instead of directly use TP
            alias = self.conn[CONN_INTERFACE_ALIASING].RequestAliases([sender])[0]
            logger.debug('%s: %s' % (alias, text))
            try:
                handle = self.chan[CHANNEL_INTERFACE_GROUP].GetHandleOwners([sender])[0]
                infos = self.conn[CONN_INTERFACE_BUDDY_INFO].GetProperties(handle)
                color = infos['color']
            except dbus.DBusException, e:
                logger.debug("failed to query buddy infos: %r" % e)
                color = "#000000,#ffffff"
            icon = CanvasIcon(
                icon_name='theme:stock-buddy',
                xo_color=XoColor(color))
            self.add_text(alias, icon, text)
        except Exception, e:
            logger.debug('failure in received_cb: %s' % e)

    def join_room(self):
        try:
            bus = dbus.Bus()
            chan_handle = self.conn[CONN_INTERFACE].RequestHandles(2, [room])[0]
            chan_path = self.conn[CONN_INTERFACE].RequestChannel(CHANNEL_TYPE_TEXT,
                2, chan_handle, True)
            self.chan = Channel(self.conn_name, chan_path)
            self.chan[CHANNEL_TYPE_TEXT].connect_to_signal('Received', self.received_cb)

            # XXX Muc shouldn't be semianonymous by default
            self.chan[PROPERTIES_INTERFACE].SetProperties([(0, False)])

        except Exception, e:
            logger.debug('failure in join_room: %s' % e)


    def status_changed_cb(self, status, reason):
        if status == CONNECTION_STATUS_CONNECTED and not self.chan:
            self.join_room()
        elif status == CONNECTION_STATUS_DISCONNECTED:
            logger.debug('disconnected')
            self.chan.Close()
            self.chan = None

    def make_root(self):
        text = hippo.CanvasText(
            text='Hello',
            font_desc=pango.FontDescription('Sans 64'),
            color=0xffffffff)

        conversation = hippo.CanvasBox(spacing=px(4))
        self.conversation = conversation

        entry = gtk.Entry()
        # XXX make this entry unsensitive while we're not
        # connected.
        entry.connect('activate', self.entry_activate_cb)

        hbox = gtk.HBox()
        hbox.add(entry)

        canvas = hippo.Canvas()
        canvas.set_root(conversation)

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        sw.add_with_viewport(canvas)
        self.scrolled_window = sw

        widget = hippo.CanvasWidget(widget=sw)

        box = gtk.VBox(homogeneous=False)
        box.pack_start(sw)
        box.pack_start(hbox, expand=False)

        return box

    def make_owner_icon(self):
        return CanvasIcon(
            icon_name='theme:stock-buddy',
            xo_color=self.owner_color)

    def add_text(self, name, icon, text):
        self._add_log(name, text)
        text = hippo.CanvasText(
            text=text,
            size_mode=hippo.CANVAS_SIZE_WRAP_WORD,
            xalign=hippo.ALIGNMENT_START)
        name = hippo.CanvasText(text=name)

        vbox = hippo.CanvasBox(padding=px(5))

        if icon:
            vbox.append(icon)

        vbox.append(name)

        rb = RoundBox(background_color=0xffffffff, padding=px(3))
        rb.append(text)

        box = hippo.CanvasBox(
            orientation=hippo.ORIENTATION_HORIZONTAL,
            spacing=px(5))
        box.append(vbox)
        box.append(rb)

        self.conversation.append(box)

        aw, ah = self.conversation.get_allocation()
        rw, rh = self.conversation.get_height_request(aw)

        adj = self.scrolled_window.get_vadjustment()
        adj.set_value(adj.upper - adj.page_size - 804)

    def entry_activate_cb(self, entry):
        text = entry.props.text
        logger.debug('Entry: %s' % text)

        if text:
            self.add_text(self.owner_nickname, self.make_owner_icon(), text)
            entry.props.text = ''

            if self.chan:
                self.chan[CHANNEL_TYPE_TEXT].Send(CHANNEL_TEXT_MESSAGE_TYPE_NORMAL, text)

    def _add_log(self, name, text):
        """Add the text to the chat log."""
        self._chat_log += '%s<%s>\t%s\n' % (
            datetime.strftime(datetime.now(), '%b %d %H:%M:%S '),
            name, text)

    def _get_log(self):
        return self._chat_log

    def write_file(self, file_path):
        """Store chat log in Journal.

        Handling the Journal is provided by Activity - we only need
        to define this method.
        """
        f = open(file_path, 'w')
        try:
            f.write(self._get_log())
        finally:
            f.close()
