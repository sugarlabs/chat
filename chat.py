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
from sugar.activity.activity import Activity, ActivityToolbox
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

from telepathy.constants import (
    CHANNEL_GROUP_FLAG_CHANNEL_SPECIFIC_HANDLES,
    CONNECTION_HANDLE_TYPE_NONE, CONNECTION_HANDLE_TYPE_CONTACT,
    CONNECTION_HANDLE_TYPE_ROOM, CHANNEL_TEXT_MESSAGE_TYPE_NORMAL,
    CONNECTION_STATUS_CONNECTED, CONNECTION_STATUS_DISCONNECTED,
    CONNECTION_STATUS_CONNECTING)

logger = logging.getLogger('chat-activity')

class Chat(Activity):
    def __init__(self, handle):
        Activity.__init__(self, handle)

        self.set_title('Chat')

        root = self.make_root()
        self.set_canvas(root)
        root.show_all()

        toolbox = ActivityToolbox(self)
        self.set_toolbox(toolbox)
        toolbox.show()

        self.owner = self._pservice.get_owner()

        # for chat logging, we want to save the log as text/plain
        # in the Journal so it will resume with the appropriate
        # activity to view the chat log.
        # XXX MorganCollett 2007/06/19: change to text/html once the
        #     browser is verified to handle that mime type
        self._chat_log = ''
        self.metadata['activity'] = ''
        self.metadata['mime_type'] = 'text/plain'

        self.connect('shared', self._shared_cb)
        self.text_channel = None
        
        if self._shared_activity:
            # we are joining the activity
            self.connect('joined', self._joined_cb)
            if self.get_shared():
                # we have already joined
                self._joined_cb()
        else:
            # we are creating the activity
            self.add_text(self.owner.props.nick,
                self._buddy_icon(self.owner), 'Connecting',
                status_message=True)
            self.share()  # Share immediately since there are no invites yet

    def _shared_cb(self, activity):
        logger.debug('Chat was shared')
        self._setup()

    def _setup(self):
        self.text_channel = TextChannelWrapper(self)
        self.text_channel.set_received_callback(self._received_cb)
        self.add_text(self.owner.props.nick, self._buddy_icon(self.owner),
            'Connected', status_message=True)
        self._shared_activity.connect('buddy-joined', self._buddy_joined_cb)
        self._shared_activity.connect('buddy-left', self._buddy_left_cb)
        self.entry.set_editable(True)

    def _joined_cb(self, activity):
        """Joined a shared activity."""
        if not self._shared_activity:
            return
        logger.debug('Joined a shared chat')
        for buddy in self._shared_activity.get_joined_buddies():
            self._buddy_already_exists(buddy)
        self._setup()

    def _received_cb(self, buddy, text):
        """Show message that was received."""
        if buddy:
            nick = buddy.props.nick
        else:
            nick = ''
        icon = self._buddy_icon(buddy)
        self.add_text(nick, icon, text)

    def _buddy_joined_cb (self, activity, buddy):
        """Show a buddy who joined"""
        if buddy == self.owner:
            return
        if buddy:
            nick = buddy.props.nick
        else:
            nick = '???'
        icon = self._buddy_icon(buddy)
        self.add_text(nick, icon, 'joined the chat',
            status_message=True)

    def _buddy_left_cb (self, activity, buddy):
        """Show a buddy who joined"""
        if buddy == self.owner:
            return
        if buddy:
            nick = buddy.props.nick
        else:
            nick = '???'
        icon = self._buddy_icon(buddy)
        self.add_text(nick, icon, 'left the chat',
            status_message=True)

    def _buddy_already_exists(self, buddy):
        """Show a buddy already in the chat."""
        if buddy == self.owner:
            return
        if buddy:
            nick = buddy.props.nick
        else:
            nick = '???'
        icon = self._buddy_icon(buddy)
        self.add_text(nick, icon, 'is here',
            status_message=True)

    def _buddy_icon(self, buddy):
        """Make a CanvasIcon for this Buddy"""
        if buddy:
            buddy_color = buddy.props.color
        else:
            buddy_color = ''
        if not buddy_color:
            buddy_color = "#000000,#ffffff"
        icon = CanvasIcon(
            icon_name='theme:stock-buddy',
            xo_color=XoColor(buddy_color))
        return icon

    def make_root(self):
        text = hippo.CanvasText(
            text='Hello',
            font_desc=pango.FontDescription('Sans 64'),
            color=0xffffffff)

        conversation = hippo.CanvasBox(spacing=px(4))
        self.conversation = conversation

        entry = gtk.Entry()
        entry.set_editable(False)
        entry.connect('activate', self.entry_activate_cb)
        self.entry = entry

        hbox = gtk.HBox()
        hbox.add(entry)

        canvas = hippo.Canvas()
        canvas.set_root(conversation)

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        sw.add_with_viewport(canvas)
        self.scrolled_window = sw
        
        vadj = self.scrolled_window.get_vadjustment()
        vadj.connect('changed', self.rescroll)        

        widget = hippo.CanvasWidget(widget=sw)

        box = gtk.VBox(homogeneous=False)
        box.pack_start(sw)
        box.pack_start(hbox, expand=False)

        return box

    def rescroll(self, adj, scroll=None):
        """Scroll the chat window to the bottom"""
        adj.set_value(adj.upper-adj.page_size)
        
    def add_text(self, name, icon, text, status_message=False):
        """Display text on screen, with name and icon.

        name -- string, buddy nick
        icon -- buddy icon - see self._buddy_icon
        text -- string, what the buddy said
        status_message -- boolean
            False: show what buddy said
            True: show what buddy did
        """
        if status_message:
            self._add_log('*', '%s %s' % (name, text))
        else:
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

        if status_message:
            rb = RoundBox(background_color=0x808080ff, padding=px(3))
        else:
            rb = RoundBox(background_color=0xffffffff, padding=px(3))
        rb.append(text)

        box = hippo.CanvasBox(
            orientation=hippo.ORIENTATION_HORIZONTAL,
            spacing=px(5))
        box.append(vbox)
        box.append(rb)

        self.conversation.append(box)

    def entry_activate_cb(self, entry):
        text = entry.props.text
        logger.debug('Entry: %s' % text)
        if text:
            self.add_text(self.owner.props.nick,
                self._buddy_icon(self.owner), text)
            entry.props.text = ''
            if self.text_channel:
                self.text_channel.send(text)
            else:
                logger.debug('Tried to send message but text channel '
                    'not connected.')

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


class TextChannelWrapper(object):
    """Wrap a telepathy text Channel to make usage simpler."""
    def __init__(self, activity):
        """Connect to the text channel if possible."""
        self._text_chan = None
        self._activity_cb = None
        self._activity = activity
        self._logger = logging.getLogger(
            'chat-activity.TextChannelWrapper')
        self._connect()

    def _connect(self):
        bus_name, conn_path, channel_paths =\
            self._activity._shared_activity.get_channels()
        for channel_path in channel_paths:
            channel = Channel(bus_name, channel_path)
            htype, handle = channel.GetHandle()
            if htype == CONNECTION_HANDLE_TYPE_ROOM:
                self._logger.debug(
                    'Found our room: it has handle#%d' % handle)
                room = handle
                ctype = channel.GetChannelType()
                if ctype == CHANNEL_TYPE_TEXT:
                    self._logger.debug(
                        'Found our Text channel at %s' % channel_path)
                    self._text_chan = channel

    def connected(self):
        return (self._text_chan is not None)

    def send(self, text):
        if self._text_chan:
            self._text_chan[CHANNEL_TYPE_TEXT].Send(
                CHANNEL_TEXT_MESSAGE_TYPE_NORMAL, text)

    def close(self):
        if self._text_chan:
            self._text_chan.Close()
            self._text_chan = None

    def set_received_callback(self, callback):
        """Connect the function callback to the signal.

        callback -- callback function taking buddy and text args
        """
        if not self._text_chan:
            self._logger.debug(
                'Failed to connect callback - text channel not connected.')
            return
        self._activity_cb = callback
        self._text_chan[CHANNEL_TYPE_TEXT].connect_to_signal('Received',
            self._received_cb)

    def _received_cb(self, id, timestamp, sender, type, flags, text):
        """Handle received text from the text channel.

        Converts sender to a Buddy.
        Calls self._activity_cb which is a callback to the activity.
        """
        if self._activity_cb:
            buddy = self._get_buddy(sender)
            self._activity_cb(buddy, text)
        else:
            self._logger.debug('Throwing received message on the floor'
                ' since there is no callback connected. See '
                'set_received_callback')

    def _get_buddy(self, cs_handle):
        """Get a Buddy from a handle."""
        tp_name, tp_path =\
            self._activity._pservice.get_preferred_connection()
        conn = Connection(tp_name, tp_path)
        group = self._text_chan[CHANNEL_INTERFACE_GROUP]
        my_csh = group.GetSelfHandle()
        if my_csh == cs_handle:
            handle = conn.GetSelfHandle()
        elif group.GetGroupFlags() & \
            CHANNEL_GROUP_FLAG_CHANNEL_SPECIFIC_HANDLES:
            handle = group.GetHandleOwners([cs_handle])[0]
        else:
            handle = cs_handle

            # XXX: deal with failure to get the handle owner
            assert handle != 0

        return self._activity._pservice.get_buddy_by_telepathy_handle(
            tp_name, tp_path, handle)
