# -*- coding: utf-8 -*-
# Copyright 2007-2008 One Laptop Per Child
# Copyright 2009-14 Sugar Labs
# Copyright 2014, Walter Bender
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

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('TelepathyGLib', '0.12')

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import TelepathyGLib
from gi.repository import GLib

try:
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
    _HAS_SOUND = True
except:
    _HAS_SOUND = False

OSK_HEIGHT = [400, 300]
SLASH = '-x-SLASH-x-'  # slash safe encoding

import logging
import json
import os
import time
from gettext import gettext as _

from sugar3.graphics import style
from sugar3.graphics.icon import EventIcon, Icon
from sugar3.graphics.alert import NotifyAlert
from sugar3.graphics.toolbarbox import ToolbarBox
from sugar3.graphics.toolbutton import ToolButton
from sugar3.activity import activity
from sugar3.activity.activity import get_bundle_path
from sugar3.presence import presenceservice
from sugar3.activity.widgets import ActivityButton, TitleEntry, \
     DescriptionItem, ShareButton, StopButton
from sugar3.activity.activity import get_activity_root
from sugar3.activity.activity import show_object_in_journal
from sugar3.datastore import datastore
from sugar3 import profile

from chat import smilies
from chat.box import ChatBox

from utils import EbookModeDetector

logger = logging.getLogger('chat-activity')


if _HAS_SOUND:
    Gst.init([])


# pylint: disable-msg=W0223
class Chat(activity.Activity):

    def __init__(self, handle):
        pservice = presenceservice.get_instance()
        self.owner = pservice.get_owner()

        self._ebook_mode_detector = EbookModeDetector()

        self.chatbox = ChatBox(
            self.owner, self._ebook_mode_detector.get_ebook_mode())
        self.chatbox.connect('open-on-journal', self.__open_on_journal)

        super(Chat, self).__init__(handle)

        self._entry = None
        self._has_alert = False
        self._has_osk = False

        self._setup_canvas()

        self._entry.grab_focus()

        toolbar_box = ToolbarBox()
        self.set_toolbar_box(toolbar_box)

        self.activity_button = ActivityButton(self)
        toolbar_box.toolbar.insert(self.activity_button, 0)
        self.activity_button.show()

        title_entry = TitleEntry(self)
        toolbar_box.toolbar.insert(title_entry, -1)
        title_entry.show()

        description_item = DescriptionItem(self)
        toolbar_box.toolbar.insert(description_item, -1)
        description_item.show()

        self._share_button = ShareButton(self)
        toolbar_box.toolbar.insert(self._share_button, -1)
        self._share_button.show()

        separator = Gtk.SeparatorToolItem()
        separator.props.draw = False
        separator.set_expand(True)
        toolbar_box.toolbar.insert(separator, -1)

        toolbar_box.toolbar.insert(StopButton(self), -1)
        toolbar_box.show_all()

        # Chat is room or one to one:
        self._chat_is_room = False
        self.text_channel = None

        if _HAS_SOUND:
            self.element = Gst.ElementFactory.make('playbin', 'Player')

        if self.shared_activity:
            # we are joining the activity following an invite
            self._entry.props.placeholder_text = \
                _('Please wait for a connection before starting to chat.')
            self.connect('joined', self._joined_cb)
            if self.get_shared():
                # we have already joined
                self._joined_cb(self)
        elif handle.uri:
            # XMPP non-sugar3 incoming chat, not sharable
            self._share_button.props.visible = False
            self._one_to_one_connection(handle.uri)
        else:
            # we are creating the activity
            if not self.metadata or self.metadata.get(
                    'share-scope', activity.SCOPE_PRIVATE) == \
                    activity.SCOPE_PRIVATE:
                # if we are in private session
                self._alert(_('Off-line'), _('Share, or invite someone.'))
            else:
                # resume of shared activity from journal object without invite
                self._entry.props.placeholder_text = \
                    _('Please wait for a connection before starting to chat.')
            self.connect('shared', self._shared_cb)

    def _fixed_resize_cb(self, widget=None, rect=None):
        ''' If a toolbar opens or closes, we need to resize the vbox
        holding out scrolling window. '''
        if self._has_alert:
            dy = style.GRID_CELL_SIZE
        else:
            dy = 0
        if self._has_osk:
            if Gdk.Screen.width() > Gdk.Screen.height():
                dy += OSK_HEIGHT[0]
            else:
                dy += OSK_HEIGHT[1]

        self.chatbox.set_size_request(self._chat_width,
                                      self._chat_height - dy)
        self._fixed.move(self._entry_grid, style.GRID_CELL_SIZE,
                         self._chat_height - dy)

        self.chatbox.resize_conversation(dy)

    def _setup_canvas(self):
        ''' Create a canvas '''
        self._fixed = Gtk.Fixed()
        self._fixed.set_size_request(
            Gdk.Screen.width(), Gdk.Screen.height() - style.GRID_CELL_SIZE)
        self._fixed.connect('size-allocate', self._fixed_resize_cb)
        self.set_canvas(self._fixed)
        self._fixed.show()

        self._entry_widgets = self._make_entry_widgets()
        self._fixed.put(self.chatbox, 0, 0)
        self.chatbox.show()

        self._fixed.put(self._entry_grid, style.GRID_CELL_SIZE,
                        self._chat_height)
        self._entry_grid.show()

        Gdk.Screen.get_default().connect('size-changed', self._configure_cb)

    def _configure_cb(self, event):
        self._fixed.set_size_request(
            Gdk.Screen.width(), Gdk.Screen.height() - style.GRID_CELL_SIZE)
        if self._ebook_mode_detector.get_ebook_mode():
            self._entry_height = int(style.GRID_CELL_SIZE * 1.5)
        else:
            self._entry_height = style.GRID_CELL_SIZE
        entry_width = Gdk.Screen.width() - \
            2 * (self._entry_height + style.GRID_CELL_SIZE)
        self._entry.set_size_request(entry_width, self._entry_height)
        self._entry_grid.set_size_request(
            Gdk.Screen.width() - 2 * style.GRID_CELL_SIZE,
            self._entry_height)

        self._chat_height = Gdk.Screen.height() - self._entry_height - \
            style.GRID_CELL_SIZE
        self._chat_width = Gdk.Screen.width()
        self.chatbox.set_size_request(self._chat_width, self._chat_height)
        self.chatbox.resize_all()

        width = int(Gdk.Screen.width() - 2 * style.GRID_CELL_SIZE)
        if self._ebook_mode_detector.get_ebook_mode():
            height = int(Gdk.Screen.height() - 8 * style.GRID_CELL_SIZE)
        else:
            height = int(Gdk.Screen.height() - 5 * style.GRID_CELL_SIZE)
        self._smiley_table.set_size_request(width, height)
        self._smiley_toolbar.set_size_request(width, -1)
        self._smiley_window.set_size_request(width, -1)

        self._fixed_resize_cb()

    def _create_smiley_table(self, width):
        pixel_size = (style.STANDARD_ICON_SIZE + style.LARGE_ICON_SIZE) / 2
        spacing = style.DEFAULT_SPACING
        button_size = pixel_size + spacing
        smilies_columns = int(width / button_size)
        pad = (width - smilies_columns * button_size) / 2

        table = Gtk.Grid()
        table.set_row_spacing(spacing)
        table.set_column_spacing(spacing)
        table.set_border_width(pad)

        queue = []
        def _create_smiley_icon_idle_cb():
            try:
                x, y, path, code = queue.pop()
            except IndexError:
                self.unbusy()
                return False
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path,
                                                            pixel_size,
                                                            pixel_size)
            image = Gtk.Image.new_from_pixbuf(pixbuf)
            box = Gtk.EventBox()
            box.add(image)
            box.connect('button-press-event', self._add_smiley_to_entry, code)
            table.attach(box, x, y, 1, 1)
            box.show_all()
            return True

        x = 0
        y = 0
        smilies.init()
        for i in range(len(smilies.THEME)):
            path, hint, codes = smilies.THEME[i]
            queue.append([x, y, path, codes[0]])

            x += 1
            if x == smilies_columns:
                y += 1
                x = 0

        queue.reverse()
        GLib.idle_add(_create_smiley_icon_idle_cb)
        return table

    def _add_smiley_to_entry(self, icon, event, text):
        pos = self._entry.props.cursor_position
        self._entry.insert_text(text, pos)
        self._entry.grab_focus()
        self._entry.set_position(pos + len(text))
        self._hide_smiley_window()

    def _shared_cb(self, sender):
        self._setup()

    def _one_to_one_connection(self, tp_channel):
        '''Handle a private invite from a non-sugar3 XMPP client.'''
        if self.shared_activity or self.text_channel:
            return
        bus_name, connection, channel = json.loads(tp_channel)
        logger.debug('GOT XMPP: %s %s %s', bus_name, connection, channel)
        conn = TelepathyGLib.Connection.new(bus_name, connection)
        self._one_to_one_connection_ready_cb(TelepathyGLib.DBusDaemon.dup(), bus_name, channel, conn)

    def _one_to_one_connection_ready_cb(self, bus_name, channel, conn):
        '''Callback for Connection for one to one connection'''
        text_channel = TelepathyGLib.Channel(conn, channel)
        self.text_channel = TextChannelWrapper(text_channel, conn)
        self.text_channel.set_received_callback(self._received_cb)
        self.text_channel.handle_pending_messages()
        self.text_channel.set_closed_callback(
            self._one_to_one_connection_closed_cb)
        self._chat_is_room = False
        self._alert(_('On-line'), _('Private Chat'))

        # XXX How do we detect the sender going offline?
        self._entry.set_sensitive(True)
        self._entry.props.placeholder_text = None
        self._entry.grab_focus()

    def _one_to_one_connection_closed_cb(self):
        '''Callback for when the text channel closes.'''
        self._alert(_('Off-line'), _('left the chat'))

    def _setup(self):
        self.text_channel = TextChannelWrapper(
            self.shared_activity.telepathy_text_chan,
            self.shared_activity.telepathy_conn)
        self.text_channel.set_received_callback(self._received_cb)
        self._alert(_('On-line'), _('Connected'))
        self.shared_activity.connect('buddy-joined', self._buddy_joined_cb)
        self.shared_activity.connect('buddy-left', self._buddy_left_cb)
        self._chat_is_room = True
        self._entry.set_sensitive(True)
        self._entry.props.placeholder_text = None
        self._entry.grab_focus()

    def _joined_cb(self, sender):
        '''Joined a shared activity.'''
        if not self.shared_activity:
            return
        logger.debug('Joined a shared chat')
        for buddy in self.shared_activity.get_joined_buddies():
            self._buddy_already_exists(buddy)
        self._setup()

    def _received_cb(self, buddy, text):
        '''Show message that was received.'''
        if buddy:
            if type(buddy) is dict:
                nick = buddy['nick']
            else:
                nick = buddy.props.nick
        else:
            nick = '???'
        logger.debug('Received message from %s: %s', nick, text)
        self.chatbox.add_text(buddy, text)

        if self.owner.props.nick in text:
            self.play_sound('said_nick')

        '''
        vscroll = self.chatbox.get_vadjustment()
        if vscroll.get_property('value') != vscroll.get_property('upper'):
            self._alert(_('New message'), _('New message from %s' % nick))
        '''
        if not self.has_focus:
            self.notify_user(_('Message from %s') % buddy, text)

    def _alert(self, title, text=None):
        alert = NotifyAlert(timeout=5)
        alert.props.title = title
        alert.props.msg = text
        self.add_alert(alert)
        alert.connect('response', self._alert_cancel_cb)
        alert.show()
        self._has_alert = True
        self._fixed_resize_cb()

    def _alert_cancel_cb(self, alert, response_id):
        self.remove_alert(alert)
        self._has_alert = False
        self._fixed_resize_cb()

    def __open_on_journal(self, widget, url):
        '''Ask the journal to display a URL'''
        logger.debug('Create journal entry for URL: %s', url)
        jobject = datastore.create()
        metadata = {
            'title': '%s: %s' % (_('URL from Chat'), url),
            'title_set_by_user': '1',
            'icon-color': profile.get_color().to_string(),
            'mime_type': 'text/uri-list',
        }
        for k, v in metadata.items():
            jobject.metadata[k] = v
        file_path = os.path.join(get_activity_root(), 'instance',
                                 '%i_' % time.time())
        open(file_path, 'w').write(url + '\r\n')
        os.chmod(file_path, 0755)
        jobject.set_file_path(file_path)
        datastore.write(jobject)
        show_object_in_journal(jobject.object_id)
        jobject.destroy()
        os.unlink(file_path)

    def _buddy_joined_cb(self, sender, buddy):
        '''Show a buddy who joined'''
        if buddy == self.owner:
            return
        self.chatbox.add_text(
            buddy, _('%s joined the chat') % buddy.props.nick,
            status_message=True)

        self.play_sound('login')

    def _buddy_left_cb(self, sender, buddy):
        '''Show a buddy who joined'''
        if buddy == self.owner:
            return
        self.chatbox.add_text(
            buddy, _('%s left the chat') % buddy.props.nick,
            status_message=True)

        self.play_sound('logout')

    def _buddy_already_exists(self, buddy):
        '''Show a buddy already in the chat.'''
        if buddy == self.owner:
            return
        self.chatbox.add_text(
            buddy, _('%s is here') % buddy.props.nick,
            status_message=True)

    def can_close(self):
        '''Perform cleanup before closing.
        Close text channel of a one to one XMPP chat.
        '''
        if self._chat_is_room is False:
            if self.text_channel is not None:
                self.text_channel.close()
        return True

    def _make_entry_widgets(self):
        '''We need to create a button for the smiley, a text entry, and a
        send button.

        All of this, along with the chatbox, goes into a grid.

        ---------------------------------------
        | chat box                            |
        | smiley button | entry | send button |
        ---------------------------------------
        '''
        if self._ebook_mode_detector.get_ebook_mode():
            self._entry_height = int(style.GRID_CELL_SIZE * 1.5)
        else:
            self._entry_height = style.GRID_CELL_SIZE
        entry_width = Gdk.Screen.width() - \
            2 * (self._entry_height + style.GRID_CELL_SIZE)
        self._chat_height = Gdk.Screen.height() - self._entry_height - \
            style.GRID_CELL_SIZE
        self._chat_width = Gdk.Screen.width()

        self.chatbox.set_size_request(self._chat_width, self._chat_height)

        self._entry_grid = Gtk.Grid()
        self._entry_grid.set_size_request(
            Gdk.Screen.width() - 2 * style.GRID_CELL_SIZE,
            self._entry_height)

        smiley_button = EventIcon(icon_name='smilies',
                                  pixel_size=self._entry_height)
        smiley_button.connect('button-press-event', self._smiley_button_cb)
        self._entry_grid.attach(smiley_button, 0, 0, 1, 1)
        smiley_button.show()

        self._entry = Gtk.Entry()
        self._entry.set_size_request(entry_width, self._entry_height)
        self._entry.modify_bg(Gtk.StateType.INSENSITIVE,
                              style.COLOR_WHITE.get_gdk_color())
        self._entry.modify_base(Gtk.StateType.INSENSITIVE,
                                style.COLOR_WHITE.get_gdk_color())

        self._entry.set_sensitive(False)
        self._entry.props.placeholder_text = \
            _('You must be connected to a friend before starting to chat.')
        self._entry.connect('focus-in-event', self._entry_focus_in_cb)
        self._entry.connect('focus-out-event', self._entry_focus_out_cb)
        self._entry.connect('activate', self._entry_activate_cb)
        self._entry.connect('key-press-event', self._entry_key_press_cb)
        self._entry_grid.attach(self._entry, 1, 0, 1, 1)
        self._entry.show()

        send_button = EventIcon(icon_name='send',
                                pixel_size=self._entry_height)
        send_button.connect('button-press-event', self._send_button_cb)
        self._entry_grid.attach(send_button, 2, 0, 1, 1)
        send_button.show()

    def _get_icon_pixbuf(self, name):
        icon_theme = Gtk.IconTheme.get_default()
        icon_info = icon_theme.lookup_icon(
            name, style.LARGE_ICON_SIZE, 0)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            icon_info.get_filename(), style.LARGE_ICON_SIZE,
            style.LARGE_ICON_SIZE)
        del icon_info
        return pixbuf

    def _entry_focus_in_cb(self, entry, event):
        self._hide_smiley_window()

        if self._ebook_mode_detector.get_ebook_mode():
            self._has_osk = True
            self._fixed_resize_cb()

    def _entry_focus_out_cb(self, entry, event):
        if self._ebook_mode_detector.get_ebook_mode():
            self._has_osk = False
            self._fixed_resize_cb()

    def _entry_key_press_cb(self, widget, event):
        '''Check for scrolling keys.

        Check if the user pressed Page Up, Page Down, Home or End and
        scroll the window according the pressed key.
        '''
        vadj = self.chatbox.get_vadjustment()
        if event.keyval == Gdk.KEY_Page_Down:
            value = vadj.get_value() + vadj.page_size
            if value > vadj.upper - vadj.page_size:
                value = vadj.upper - vadj.page_size
            vadj.set_value(value)
        elif event.keyval == Gdk.KEY_Page_Up:
            vadj.set_value(vadj.get_value() - vadj.page_size)
        elif event.keyval == Gdk.KEY_Home and \
                event.get_state() & Gdk.ModifierType.CONTROL_MASK:
            vadj.set_value(vadj.lower)
        elif event.keyval == Gdk.KEY_End and \
                event.get_state() & Gdk.ModifierType.CONTROL_MASK:
            vadj.set_value(vadj.upper - vadj.page_size)

    def _smiley_button_cb(self, widget, event):
        self._show_smiley_window()

    def _send_button_cb(self, widget, event):
        self._entry_activate_cb(self._entry)

    def _entry_activate_cb(self, entry):
        self.chatbox._scroll_auto = True

        text = entry.props.text
        if text:
            logger.debug('Adding text to chatbox: %s: %s' % (self.owner, text))
            self.chatbox.add_text(self.owner, text)
            entry.props.text = ''
            if self.text_channel:
                logger.debug('sending to text_channel: %s' % (text))
                self.text_channel.send(text)
            else:
                logger.debug('Tried to send message but text channel '
                             'not connected.')

    def write_file(self, file_path):
        '''Store chat log in Journal.

        Handling the Journal is provided by Activity - we only need
        to define this method.
        '''
        logger.debug('write_file: writing %s' % file_path)
        self.chatbox.add_log_timestamp()
        f = open(file_path, 'w')
        try:
            f.write(self.chatbox.get_log())
        finally:
            f.close()
        self.metadata['mime_type'] = 'text/plain'

    def read_file(self, file_path):
        '''Load a chat log from the Journal.
        Handling the Journal is provided by Activity - we only need
        to define this method.
        '''
        logger.debug('read_file: reading %s' % file_path)
        log = open(file_path).readlines()
        last_line_was_timestamp = False
        for line in log:
            if line.endswith('\t\t\n'):
                if last_line_was_timestamp is False:
                    timestamp = line.strip().split('\t')[0]
                    self.chatbox.add_separator(timestamp)
                    last_line_was_timestamp = True
            else:
                timestamp, nick, color, status, text = line.strip().split('\t')
                status_message = bool(int(status))
                self.chatbox.add_text({'nick': nick, 'color': color},
                                      text, status_message)
                last_line_was_timestamp = False

    def play_sound(self, event):
        if _HAS_SOUND:
            SOUNDS_PATH = os.path.join(get_bundle_path(), 'sounds')
            SOUNDS = {'said_nick': os.path.join(SOUNDS_PATH, 'alert.wav'),
                      'login': os.path.join(SOUNDS_PATH, 'login.wav'),
                      'logout': os.path.join(SOUNDS_PATH, 'logout.wav')}

            self.element.set_state(Gst.State.NULL)
            self.element.set_property('uri', 'file://%s' % SOUNDS[event])
            self.element.set_state(Gst.State.PLAYING)

    def _create_smiley_window(self):
        grid = Gtk.Grid()
        width = int(Gdk.Screen.width() - 2 * style.GRID_CELL_SIZE)

        self._smiley_toolbar = SmileyToolbar(self)
        height = style.GRID_CELL_SIZE
        self._smiley_toolbar.set_size_request(width, height)
        grid.attach(self._smiley_toolbar, 0, 0, 1, 1)
        self._smiley_toolbar.show()

        self._smiley_table = Gtk.ScrolledWindow()
        self._smiley_table.set_policy(Gtk.PolicyType.NEVER,
                                      Gtk.PolicyType.AUTOMATIC)
        self._smiley_table.modify_bg(
            Gtk.StateType.NORMAL, style.COLOR_BLACK.get_gdk_color())
        if self._ebook_mode_detector.get_ebook_mode():
            height = int(Gdk.Screen.height() - 8 * style.GRID_CELL_SIZE)
        else:
            height = int(Gdk.Screen.height() - 4 * style.GRID_CELL_SIZE)
        self._smiley_table.set_size_request(width, height)

        table = self._create_smiley_table(width)
        self._smiley_table.add_with_viewport(table)
        table.show_all()

        grid.attach(self._smiley_table, 0, 1, 1, 1)
        self._smiley_table.show()

        self._smiley_window = Gtk.ScrolledWindow()
        self._smiley_window.set_policy(Gtk.PolicyType.NEVER,
                                       Gtk.PolicyType.NEVER)
        self._smiley_window.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        self._smiley_window.set_size_request(width, -1)

        self._smiley_window.add_with_viewport(grid)

        def _key_press_event_cb(widget, event):
            if event.keyval == Gdk.KEY_Escape:
                self._hide_smiley_window()
                return True
            return False
        self.connect('key-press-event', _key_press_event_cb)

        grid.show()

        self._fixed.put(self._smiley_window, style.GRID_CELL_SIZE, 0)

    def _show_smiley_window(self):
        if not hasattr(self, '_smiley_window'):
            self.busy()
            self._create_smiley_window()
        self._smiley_window.show()

    def _hide_smiley_window(self):
        if hasattr(self, '_smiley_window'):
            self._smiley_window.hide()


class TextChannelWrapper(object):
    '''Wrap a telepathy Text Channfel to make usage simpler.'''

    def __init__(self, text_chan, conn):
        '''Connect to the text channel'''
        self._activity_cb = None
        self._activity_close_cb = None
        self._text_chan = text_chan
        self._conn = conn
        self._logger = logging.getLogger(
            'chat-activity.TextChannelWrapper')
        self._signal_matches = []
        m = self._text_chan[TelepathyGLib.IFACE_CHANNEL].connect_to_signal(
            'Closed', self._closed_cb)
        self._signal_matches.append(m)

    def send(self, text):
        '''Send text over the Telepathy text channel.'''
        # XXX Implement CHANNEL_TEXT_MESSAGE_TYPE_ACTION
        logging.debug('sending %s' % text)

        text = text.replace('/', SLASH)

        if self._text_chan is not None:
            self._text_chan[TelepathyGLib.IFACE_CHANNEL_TYPE_TEXT].Send(
                TelepathyGLib.ChannelTextMessageType.NORMAL, text)

    def close(self):
        '''Close the text channel.'''
        self._logger.debug('Closing text channel')
        try:
            self._text_chan[TelepathyGLib.IFACE_CHANNEL].Close()
        except Exception:
            self._logger.debug('Channel disappeared!')
            self._closed_cb()

    def _closed_cb(self):
        '''Clean up text channel.'''
        self._logger.debug('Text channel closed.')
        for match in self._signal_matches:
            match.remove()
        self._signal_matches = []
        self._text_chan = None
        if self._activity_close_cb is not None:
            self._activity_close_cb()

    def set_received_callback(self, callback):
        '''Connect the function callback to the signal.

        callback -- callback function taking buddy and text args
        '''
        if self._text_chan is None:
            return
        self._activity_cb = callback
        m = self._text_chan[TelepathyGLib.IFACE_CHANNEL_TYPE_TEXT].connect_to_signal(
            'Received', self._received_cb)
        self._signal_matches.append(m)

    def handle_pending_messages(self):
        '''Get pending messages and show them as received.'''
        for identity, timestamp, sender, type_, flags, text in \
            self._text_chan[
                TelepathyGLib.IFACE_CHANNEL_TYPE_TEXT].ListPendingMessages(False):
            self._received_cb(identity, timestamp, sender, type_, flags, text)

    def _received_cb(self, identity, timestamp, sender, type_, flags, text):
        '''Handle received text from the text channel.

        Converts sender to a Buddy.
        Calls self._activity_cb which is a callback to the activity.
        '''
        logging.debug('received_cb %r %s' % (type_, text))
        if type_ != 0:
            # Exclude any auxiliary messages
            return

        text = text.replace(SLASH, '/')

        if self._activity_cb:
            try:
                self._text_chan[TelepathyGLib.IFACE_CHANNEL_INTERFACE_GROUP]
            except Exception:
                # One to one XMPP chat
                nick = self._conn[
                    TelepathyGLib.IFACE_CONNECTION_INTERFACE_ALIASING].RequestAliases([sender])[0]
                buddy = {'nick': nick, 'color': '#000000,#808080'}
            else:
                # Normal sugar3 MUC chat
                # XXX: cache these
                buddy = self._get_buddy(sender)
            self._activity_cb(buddy, text)
            self._text_chan[
                TelepathyGLib.IFACE_CHANNEL_TYPE_TEXT].AcknowledgePendingMessages([identity])
        else:
            self._logger.debug('Throwing received message on the floor'
                               ' since there is no callback connected. See'
                               ' set_received_callback')

    def set_closed_callback(self, callback):
        '''Connect a callback for when the text channel is closed.

        callback -- callback function taking no args

        '''
        self._activity_close_cb = callback

    def _get_buddy(self, cs_handle):
        '''Get a Buddy from a (possibly channel-specific) handle.'''
        # XXX This will be made redundant once Presence Service
        # provides buddy resolution
        # Get the Presence Service
        pservice = presenceservice.get_instance()
        # Get the Telepathy Connection
        tp_name, tp_path = pservice.get_preferred_connection()
        conn = TelepathyGLib.Connection.new(TelepathyGLib.DBusDaemon.dup(), tp_name, tp_path)
        group = self._text_chan[TelepathyGLib.IFACE_CHANNEL_INTERFACE_GROUP]
        my_csh = group.GetSelfHandle()
        if my_csh == cs_handle:
            handle = conn.GetSelfHandle()
        elif group.GetGroupFlags() & \
                TelepathyGLib.ChannelGroupFlags.CHANNEL_SPECIFIC_HANDLES:

            handle = group.GetHandleOwners([cs_handle])[0]
        else:
            handle = cs_handle

            # XXX: deal with failure to get the handle owner
            assert handle != 0

        return pservice.get_buddy_by_telepathy_handle(
            tp_name, tp_path, handle)


class SmileyToolbar(Gtk.Toolbar):

    def __init__(self, activity):
        Gtk.Toolbar.__init__(self)

        self._activity = activity
        self._add_separator()

        self._icon = Icon(icon_name='smilies-white')
        self._add_widget(self._icon)

        self._add_separator()

        self._title = Gtk.Label(_('Insert a smiley'))
        self._add_widget(self._title)

        self._add_separator(True)

        self.cancel_button = ToolButton('dialog-cancel')
        self.cancel_button.set_tooltip(_('Cancel'))
        self.cancel_button.connect('clicked', self.__cancel_button_clicked_cb)
        self.insert(self.cancel_button, -1)
        self.cancel_button.show()

    def _add_separator(self, expand=False):
        separator = Gtk.SeparatorToolItem()
        separator.props.draw = False
        if expand:
            separator.set_expand(True)
        else:
            separator.set_size_request(style.DEFAULT_SPACING, -1)
        self.insert(separator, -1)
        separator.show()

    def _add_widget(self, widget, expand=False):
        tool_item = Gtk.ToolItem()
        tool_item.set_expand(expand)

        tool_item.add(widget)
        widget.show()

        self.insert(tool_item, -1)
        tool_item.show()

    def __cancel_button_clicked_cb(self, widget, data=None):
        self._activity._hide_smiley_window()
