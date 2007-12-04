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

from gettext import gettext as _
import dbus
import hippo
import gtk
import pango
import logging
import re
from datetime import datetime

from sugar import profile
from sugar.activity.activity import Activity, ActivityToolbox
from sugar.graphics.alert import NotifyAlert
from sugar.graphics.style import (Color, COLOR_BLACK, COLOR_WHITE, 
    FONT_BOLD, FONT_NORMAL)
from sugar.graphics.roundbox import CanvasRoundBox
from sugar.graphics.xocolor import XoColor
from sugar.graphics.palette import Palette, CanvasInvoker
from sugar.graphics.menuitem import MenuItem
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

        root = self.make_root()
        self.set_canvas(root)
        root.show_all()
        self.entry.grab_focus()

        toolbox = ActivityToolbox(self)
        self.set_toolbox(toolbox)
        toolbox.show()

        self.owner = self._pservice.get_owner()
        self._chat_log = ''
        # Auto vs manual scrolling:
        self._scroll_auto = True
        self._scroll_value = 0.0

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
            self._alert(_('Off-line'), _('Share, or invite someone.'))

    def _shared_cb(self, activity):
        logger.debug('Chat was shared')
        self._setup()

    def _setup(self):
        self.text_channel = TextChannelWrapper(self)
        self.text_channel.set_received_callback(self._received_cb)
        self._alert(_('On-line'), _('Connected'))
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
            nick = '???'
        self.add_text(buddy, text)

    def _alert(self, title, text=None):
        alert = NotifyAlert(timeout=5)
        alert.props.title = title
        alert.props.msg = text
        self.add_alert(alert)
        alert.connect('response', self._alert_cancel_cb)
        alert.show()

    def _alert_cancel_cb(self, alert, response_id):
        self.remove_alert(alert)

    def _buddy_joined_cb (self, activity, buddy):
        """Show a buddy who joined"""
        if buddy == self.owner:
            return
        if buddy:
            nick = buddy.props.nick
        else:
            nick = '???'
        self.add_text(buddy, buddy.props.nick+' '+_('joined the chat'),
            status_message=True)

    def _buddy_left_cb (self, activity, buddy):
        """Show a buddy who joined"""
        if buddy == self.owner:
            return
        if buddy:
            nick = buddy.props.nick
        else:
            nick = '???'
        self.add_text(buddy, buddy.props.nick+' '+_('left the chat'),
            status_message=True)

    def _buddy_already_exists(self, buddy):
        """Show a buddy already in the chat."""
        if buddy == self.owner:
            return
        if buddy:
            nick = buddy.props.nick
        else:
            nick = '???'
        self.add_text(buddy, buddy.props.nick+' '+_('is here'),
            status_message=True)

    def make_root(self):
        conversation = hippo.CanvasBox(
            spacing=4,
            background_color=COLOR_WHITE.get_int())
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
        vadj.connect('value-changed', self.scroll_value_changed_cb)

        widget = hippo.CanvasWidget(widget=sw)

        box = gtk.VBox(homogeneous=False)
        box.pack_start(sw)
        box.pack_start(hbox, expand=False)

        return box

    def rescroll(self, adj, scroll=None):
        """Scroll the chat window to the bottom"""
        if self._scroll_auto:
            adj.set_value(adj.upper-adj.page_size)
            self._scroll_value = adj.get_value()

    def scroll_value_changed_cb(self, adj, scroll=None):
        """Turn auto scrolling on or off.
        
        If the user scrolled up, turn it off.
        If the user scrolled to the bottom, turn it back on.
        """
        if adj.get_value() < self._scroll_value:
            self._scroll_auto = False
        elif adj.get_value() == adj.upper-adj.page_size:
            self._scroll_auto = True

    def add_text(self, buddy, text, status_message=False):
        """Display text on screen, with name and colors.

        buddy -- buddy object or dict {nick: string, color: string}
        text -- string, what the buddy said
        status_message -- boolean
            False: show what buddy said
            True: show what buddy did
        """
        if buddy:
            if type(buddy) is dict:
                nick = buddy['nick']
                color = buddy['color']
            else:
                nick = buddy.props.nick
                color = buddy.props.color
            try:
                color_stroke, color_fill = color.split(',')
            except ValueError:
                color_stroke, color_fill = ('#000000', '#888888')
            color_stroke = Color(color_stroke).get_int()
            color_fill = Color(color_fill).get_int()
            text_color = COLOR_WHITE.get_int()
            self._add_log(nick, color, text, status_message)
        else:
            nick = '???'  # XXX: should be '' but leave for debugging
            color_stroke = COLOR_BLACK.get_int()
            color_fill = COLOR_WHITE.get_int()
            text_color = COLOR_BLACK.get_int()

        rb = CanvasRoundBox(background_color=color_fill,
                            border_color=color_stroke,
                            padding=4)
        rb.props.border_color = color_stroke  # Bug #3742

        if not status_message:
            name = hippo.CanvasText(text=nick+':   ',
                color=text_color,
                font_desc=FONT_BOLD.get_pango_desc())
            rb.append(name)

        regexp = re.compile('((http|ftp)s?://)?'
        '(([-a-zA-Z0-9]+[.])+[-a-zA-Z0-9]{2,}|([0-9]{1,3}[.]){3}[0-9]{1,3})'
        '(:[1-9][0-9]{0,4})?(/[-a-zA-Z0-9/%~@&_+=;:,.?#]*[a-zA-Z0-9/])?')
        match = regexp.search(text)
        while match:
            # there is a URL in the text
            starttext = text[:match.start()]
            if starttext:
                message = hippo.CanvasText(
                    text=starttext,
                    size_mode=hippo.CANVAS_SIZE_WRAP_WORD,
                    color=text_color,
                    font_desc=FONT_NORMAL.get_pango_desc(),
                    xalign=hippo.ALIGNMENT_START)
                rb.append(message)
            url = text[match.start():match.end()]
            message = hippo.CanvasLink(
                text=url,
                color=text_color,
                font_desc=FONT_BOLD.get_pango_desc(),
                )
            attrs = pango.AttrList()
            attrs.insert(pango.AttrUnderline(pango.UNDERLINE_SINGLE, 0, 32767))
            message.set_property("attributes", attrs)

            palette = URLMenu(url)
            palette.props.invoker = CanvasInvoker(message)

            rb.append(message)
            text = text[match.end():]
            match = regexp.search(text)
        if text:
            message = hippo.CanvasText(
                text=text,
                size_mode=hippo.CANVAS_SIZE_WRAP_WORD,
                color=text_color,
                font_desc=FONT_NORMAL.get_pango_desc(),
                xalign=hippo.ALIGNMENT_START)
            rb.append(message)

        box = hippo.CanvasBox(padding=4)
        box.append(rb)
        self.conversation.append(box)

    def entry_activate_cb(self, entry):
        text = entry.props.text
        logger.debug('Entry: %s' % text)
        if text:
            self.add_text(self.owner, text)
            entry.props.text = ''
            if self.text_channel:
                self.text_channel.send(text)
            else:
                logger.debug('Tried to send message but text channel '
                    'not connected.')

    def _add_log(self, nick, color, text, status_message):
        """Add the text to the chat log.
        
        nick -- string, buddy nickname
        color -- string, buddy.props.color
        text -- string, body of message
        status_message -- boolean
        """
        self._chat_log += '%s\t%s\t%s\t%d\t%s\n' % (
            datetime.strftime(datetime.now(), '%b %d %H:%M:%S'),
            nick, color, status_message, text)

    def _get_log(self):
        return self._chat_log

    def write_file(self, file_path):
        """Store chat log in Journal.

        Handling the Journal is provided by Activity - we only need
        to define this method.
        """
        logger.debug('write_file: writing %s' % file_path)
        f = open(file_path, 'w')
        try:
            f.write(self._get_log())
        finally:
            f.close()

    def read_file(self, file_path):
        """Load a chat log from the Journal.

        Handling the Journal is provided by Activity - we only need
        to define this method.
        """
        logger.debug('read_file: reading %s' % file_path)
        log = open(file_path).readlines()
        for line in log:
            timestamp, nick, color, status, text = line.strip().split('\t')
            status_message = bool(int(status))
            self.add_text({'nick': nick, 'color': color},
                          text, status_message)


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
            # XXX: cache these
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

class URLMenu(Palette):
    def __init__(self, url):
        Palette.__init__(self, url)

        protocols = ['http://', 'https://', 'ftp://', 'ftps://']
        no_protocol = True
        for protocol in protocols:
            if url.startswith(protocol):
                no_protocol = False
        if no_protocol:
            url = 'http://' + url
        self.url = url

        menu_item = MenuItem(_('Copy to Clipboard'), 'edit-copy')
        menu_item.connect('activate', self._copy_to_clipboard_cb)
        self.menu.append(menu_item)
        menu_item.show()

    def _copy_to_clipboard_cb(self, menuitem):
        logger.debug('Copy %s to clipboard', self.url)
        clipboard = gtk.clipboard_get()
        targets = [("text/uri-list", 0, 0)]

        if not clipboard.set_with_data(targets,
                                       self._clipboard_data_get_cb,
                                       self._clipboard_clear_cb,
                                       (self.url)):
            logger.error('GtkClipboard.set_with_data failed!')
        else:
            self.owns_clipboard = True

    def _clipboard_data_get_cb(self, clipboard, selection, info, data):
        logger.debug('_clipboard_data_get_cb data=%s target=%s', data,
                     selection.target)        
        if selection.target in ['text/uri-list']:
            if not selection.set_uris([data]):
                logger.debug('failed to set_uris')
        else:
            logger.debug('not uri')
            if not selection.set_text(data):
                logger.debug('failed to set_text')

    def _clipboard_clear_cb(self, clipboard, data):
        logger.debug('clipboard_clear_cb')
        self.owns_clipboard = False
