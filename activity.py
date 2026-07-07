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
gi.require_version('Gtk', '4.0')
gi.require_version('TelepathyGLib', '0.12')

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import TelepathyGLib
from gi.repository import GLib

gi.require_version('Gst', '1.0')
from gi.repository import Gst

OSK_HEIGHT = [400, 300]
SLASH = '-x-SLASH-x-'  # slash safe encoding
import logging
import json
import os
import time
import dbus
import re
from gettext import gettext as _

def _get_screen_width():
    display = Gdk.Display.get_default()
    if display:
        monitors = display.get_monitors()
        if monitors and monitors.get_n_items() > 0:
            return monitors.get_item(0).get_geometry().width
    return 1200

def _get_screen_height():
    display = Gdk.Display.get_default()
    if display:
        monitors = display.get_monitors()
        if monitors and monitors.get_n_items() > 0:
            return monitors.get_item(0).get_geometry().height
    return 900

from sugar4.graphics import style
from sugar4.graphics.icon import EventIcon, Icon
from sugar4.graphics.alert import NotifyAlert
from sugar4.graphics.toolbarbox import ToolbarBox
from sugar4.graphics.toolbutton import ToolButton
from sugar4.activity import activity
from sugar4.activity.activity import get_bundle_path
from sugar4.presence import presenceservice
from sugar4.activity.widgets import ActivityToolbarButton
from sugar4.activity.widgets import StopButton
from sugar4.activity.activity import get_activity_root
from sugar4.activity.activity import show_object_in_journal
from sugar4.datastore import datastore
from sugar4 import profile
from sugar4.graphics import iconentry

from chat import smilies
from chat.box import ChatBox

logger = logging.getLogger('chat-activity')


Gst.init([])


# pylint: disable-msg=W0223
class Chat(activity.Activity):

    def __init__(self, handle):
        pservice = presenceservice.get_instance()
        self.owner = pservice.get_owner()

        self.chatbox = ChatBox(self.owner)
        self.chatbox.connect('open-on-journal', self.__open_on_journal)
        self.chatbox.connect('new-message',
                             self._search_entry_on_new_message_cb)

        super(Chat, self).__init__(handle)

        self._entry = None
        self._has_alert = False

        self._setup_canvas()

        self._entry.grab_focus()

        toolbar_box = ToolbarBox()
        self.set_toolbar_box(toolbar_box)

        self._activity_toolbar_button = ActivityToolbarButton(self)
        self._activity_toolbar_button.connect('clicked', self._fixed_resize_cb)

        toolbar_box.toolbar.prepend(self._activity_toolbar_button)
        self._activity_toolbar_button.show()

        self.search_entry = iconentry.IconEntry()
        self.search_entry.set_size_request(int(_get_screen_width() / 3), -1)
        self.search_entry.set_icon_from_name(
            iconentry.ICON_ENTRY_PRIMARY, 'entry-search')
        self.search_entry.add_clear_button()
        self.search_entry.connect('activate', self._search_entry_activate_cb)
        self.search_entry.connect('changed', self._search_entry_activate_cb)

        self.key_ctrl = Gtk.EventControllerKey.new()
        self.key_ctrl.connect("key-pressed", self._window_key_press_cb)
        self.add_controller(self.key_ctrl)

        self._search_item = Gtk.Box()
        self._search_item.append(self.search_entry)
        toolbar_box.toolbar.append(self._search_item)

        self._search_prev = ToolButton('go-previous-paired')
        self._search_prev.set_tooltip(_('Previous'))
        self._search_prev.props.accelerator = "<Shift><Ctrl>g"
        self._search_prev.connect('clicked', self._search_prev_cb)
        self._search_prev.props.sensitive = False
        toolbar_box.toolbar.append(self._search_prev)

        self._search_next = ToolButton('go-next-paired')
        self._search_next.set_tooltip(_('Next'))
        self._search_next.props.accelerator = "<Ctrl>g"
        self._search_next.connect('clicked', self._search_next_cb)
        self._search_next.props.sensitive = False
        toolbar_box.toolbar.append(self._search_next)

        separator = Gtk.Box()
        separator.set_hexpand(True)
        toolbar_box.toolbar.append(separator)

        toolbar_box.toolbar.append(StopButton(self))
        toolbar_box.show()

        # Chat is room or one to one:
        self._chat_is_room = False
        self.text_channel = None

        self.element = Gst.ElementFactory.make('playbin', 'Player')

        if self.shared_activity:
            # we are joining the activity following an invite
            self._alert(_('Off-line'), _('Joining the Chat.'))
            self._entry.props.placeholder_text = \
                _('Please wait for a connection before starting to chat.')
            self.connect('joined', self._joined_cb)
            if self.get_shared():
                # we have already joined
                self._joined_cb(self)
        elif handle.uri:
            # XMPP non-sugar4 incoming chat, not sharable
            self._activity_toolbar_button.props.page.share.props.visible = \
                False
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

    def _window_key_press_cb(self, controller, keyval, keycode, state):
        keyname = Gdk.keyval_name(keyval).lower()
        if keyname == 'f':
            if Gdk.ModifierType.CONTROL_MASK & state:
                self.search_entry.grab_focus()
                return True
        elif keyname == 'escape':
            if hasattr(self, '_main_stack') and \
                    self._main_stack.get_visible_child_name() == "smiley_window":
                self._hide_smiley_window()
                return True
            self.search_entry.props.text = ''
            self._entry.grab_focus()
            return True
        return False

    def _search_entry_on_new_message_cb(self, chatbox):
        self._search_entry_activate_cb(self.search_entry)

    def _search_entry_activate_cb(self, entry):
        for i in range(0, self.chatbox.number_of_textboxes()):
            textbox = self.chatbox.get_textbox(i)
            _buffer = textbox.get_buffer()
            start_mark = _buffer.get_mark('start')
            end_mark = _buffer.get_mark('end')
            if start_mark is None or end_mark is None:
                continue
            _buffer.delete_mark(start_mark)
            _buffer.delete_mark(end_mark)
            self.chatbox.highlight_text = (None, None, None)
        self.chatbox.set_search_text(entry.props.text)
        self._update_search_buttons()

    def _update_search_buttons(self):
        if len(self.chatbox.search_text) == 0:
            self._search_prev.props.sensitive = False
            self._search_next.props.sensitive = False
        else:
            # If next or previous result exists
            self._search_prev.props.sensitive = \
                self.chatbox.check_next('backward')
            self._search_next.props.sensitive = \
                self.chatbox.check_next('forward')

    def _search_prev_cb(self, button):
        if button.props.sensitive:
            self.chatbox.search('backward')
            self._update_search_buttons()

    def _search_next_cb(self, button):
        if button.props.sensitive:
            self.chatbox.search('forward')
            self._update_search_buttons()

    def _setup_canvas(self):
        ''' Create a canvas '''
        
        # Setup application CSS once
        css_provider = Gtk.CssProvider()
        bg_black = style.COLOR_BLACK.get_html()
        bg_grey = style.COLOR_TOOLBAR_GREY.get_html()
        fg_white = style.COLOR_WHITE.get_html()
        css = (f".smiley-table-black {{ background-color: {bg_black}; }}\n"
               f".smiley-toolbar-grey {{ background-color: {bg_grey}; color: {fg_white}; }}")
        css_provider.load_from_data(css.encode('utf-8'))
        display = Gdk.Display.get_default()
        if hasattr(Gtk, 'display_add_provider'):
            Gtk.display_add_provider(display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        else:
            Gtk.StyleContext.add_provider_for_display(
                display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_canvas(self._vbox)
        self._vbox.show()

        self._make_entry_widgets()

        self.chatbox.set_vexpand(True)
        self.chatbox.set_hexpand(True)

        # Create a Gtk.Stack to swap between chatbox and smiley window
        self._main_stack = Gtk.Stack()
        self._main_stack.set_vexpand(True)
        self._main_stack.set_hexpand(True)
        self._main_stack.add_named(self.chatbox, "chatbox")
        
        self._vbox.append(self._main_stack)
        self.chatbox.show()
        self._main_stack.show()

        self._vbox.append(self._entry_grid)
        self._entry_grid.show()

        display = Gdk.Display.get_default()
        if display:
            display.get_monitors().connect('items-changed', self._configure_cb)
        self.connect('notify::default-width', self._configure_cb)

    def _configure_cb(self, *args):
        # *args silently absorbs the (model, position, removed, added) from items-changed
        self._entry_height = style.GRID_CELL_SIZE
        entry_width = int(_get_screen_width() - 2 * (self._entry_height + style.GRID_CELL_SIZE))
        self._entry.set_size_request(entry_width, self._entry_height)
        self._entry_grid.set_size_request(int(_get_screen_width() - 2 * style.GRID_CELL_SIZE), self._entry_height)

        self._chat_width = int(_get_screen_width())
        self._chat_height = int(_get_screen_height() - (self._entry_height + 2 * style.GRID_CELL_SIZE))

        self.chatbox.resize_all()

        self._fixed_resize_cb()

    def _fixed_resize_cb(self, widget=None, rect=None):
        ''' If a toolbar opens or closes, we need to resize the vbox
        holding our scrolling window. '''
        if self._has_alert:
            dy = style.GRID_CELL_SIZE
        else:
            dy = 0

        if self._toolbar_expanded():
            dy += style.GRID_CELL_SIZE

        if hasattr(self, '_chat_width') and hasattr(self, '_chat_height'):
            self.chatbox.set_size_request(self._chat_width, self._chat_height - dy)

        self.chatbox.resize_conversation(dy)

    def _toolbar_expanded(self):
        if hasattr(self, '_activity_toolbar_button') and self._activity_toolbar_button.is_expanded():
            return True
        return False

    def _create_smiley_table(self, width):
        # Calculate the exact size so the emojis scale correctly with the Sugar theme
        pixel_size = int((style.STANDARD_ICON_SIZE + style.LARGE_ICON_SIZE) / 2)
        spacing = style.DEFAULT_SPACING
        button_size = pixel_size + spacing
        smilies_columns = max(1, int(width / button_size))

        table = Gtk.Grid()
        table.set_row_spacing(spacing)
        table.set_column_spacing(spacing)
        
        # Center the grid block so columns don't stretch and create huge gaps!
        table.set_halign(Gtk.Align.CENTER)
        
        table.set_margin_top(spacing)
        table.set_margin_bottom(spacing)

        queue = []

        def _create_smiley_icon_idle_cb():
            try:
                x, y, path, code = queue.pop()
            except IndexError:
                self.unbusy()
                return False

            # Load at double resolution (128x128) to ensure sharpness on high-DPI screens.
            # CRITICAL: Older SVGs lack a viewBox, causing modern librsvg to refuse to scale them.
            # We must dynamically inject a viewBox based on the width/height to force scaling!
            with open(path, 'rb') as f:
                svg_data = f.read().decode('utf-8', errors='ignore')
                
            if 'viewBox' not in svg_data:
                w_match = re.search(r'(?i)width="([0-9.]+)[a-z]*"', svg_data)
                h_match = re.search(r'(?i)height="([0-9.]+)[a-z]*"', svg_data)
                if w_match and h_match:
                    w = w_match.group(1)
                    h = h_match.group(1)
                    svg_data = svg_data.replace('<svg', f'<svg viewBox="0 0 {w} {h}"', 1)
            
            loader = GdkPixbuf.PixbufLoader.new_with_type('svg')
            loader.set_size(pixel_size * 2, pixel_size * 2)
            loader.write(svg_data.encode('utf-8'))
            loader.close()
            pixbuf = loader.get_pixbuf()
            
            if hasattr(Gdk, 'MemoryTexture') and hasattr(GLib, 'Bytes'):
                has_alpha = pixbuf.get_has_alpha()
                format = Gdk.MemoryFormat.R8G8B8A8 if has_alpha else Gdk.MemoryFormat.R8G8B8
                bytes_data = GLib.Bytes.new(pixbuf.get_pixels())
                texture = Gdk.MemoryTexture.new(
                    pixbuf.get_width(),
                    pixbuf.get_height(),
                    format,
                    bytes_data,
                    pixbuf.get_rowstride()
                )
            else:
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            del pixbuf # Free pixbuf memory early
            
            # Gtk.Picture allows us to display the large texture safely scaled down into logical pixels
            picture = Gtk.Picture.new_for_paintable(texture)
            picture.set_size_request(pixel_size, pixel_size)
            picture.set_can_shrink(True)
            
            box = Gtk.Box()
            box.append(picture)
            gesture = Gtk.GestureClick.new()
            # Properly bind box and code to the lambda to avoid closure scope leaks
            gesture.connect('pressed', lambda g, n, dx, dy, b=box, c=code: self._add_smiley_to_entry(b, c))
            box.add_controller(gesture)
            table.attach(box, x, y, 1, 1)
            box.show()
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

    def _create_smiley_window(self):
        self._smiley_window = Gtk.Grid()

        # Indent the entire window to create white margins on the sides
        margin = style.GRID_CELL_SIZE
        width = int((_get_screen_width()) - 2 * margin)
        self._smiley_window.set_margin_start(margin)
        self._smiley_window.set_margin_end(margin)

        self._smiley_toolbar = SmileyToolbar(self)
        self._smiley_toolbar.set_hexpand(True)
        self._smiley_window.attach(self._smiley_toolbar, 0, 0, 1, 1)
        self._smiley_toolbar.show()

        self._smiley_table = Gtk.ScrolledWindow()
        self._smiley_table.add_css_class("smiley-table-black")
        
        # Force the vertical scrollbar to be permanently visible
        self._smiley_table.set_policy(Gtk.PolicyType.NEVER,
                                      Gtk.PolicyType.ALWAYS)
        
        # Disable overlay scrolling so the scrollbar is permanently visible
        self._smiley_table.set_overlay_scrolling(False)
        
        self._smiley_table.set_vexpand(True)
        self._smiley_table.set_hexpand(True)

        table = self._create_smiley_table(width)
        self._smiley_table.set_child(table)
        self._smiley_window.attach(self._smiley_table, 0, 1, 1, 1)
        self._smiley_table.show()
        table.show()

        self._smiley_window.show()
        
        self._main_stack.add_named(self._smiley_window, "smiley_window")

    def _add_smiley_to_entry(self, icon, text):
        pos = self._entry.props.cursor_position
        self._entry.insert_text(text, pos)
        self._entry.grab_focus()
        self._entry.set_position(pos + len(text))
        self._hide_smiley_window()

    def _shared_cb(self, sender):
        self._setup()

    def _one_to_one_connection(self, tp_channel):
        '''Handle a private invite from a non-sugar4 XMPP client.'''
        if self.shared_activity or self.text_channel:
            return
        bus_name, connection, channel = json.loads(tp_channel)
        logger.debug('GOT XMPP: %s %s %s', bus_name, connection, channel)
        conn = {}
        conn_proxy = dbus.Bus().get_object(bus_name, connection)
        conn[TelepathyGLib.IFACE_CONNECTION_INTERFACE_ALIASING] = \
            dbus.Interface(
                conn_proxy, TelepathyGLib.IFACE_CONNECTION_INTERFACE_ALIASING)
        self._one_to_one_connection_ready_cb(bus_name, channel, conn)

    def _one_to_one_connection_ready_cb(self, bus_name, channel, conn):
        '''Callback for Connection for one to one connection'''
        text_channel = {}
        text_proxy = dbus.Bus().get_object(bus_name, channel)
        text_channel[TelepathyGLib.IFACE_CHANNEL] = \
            dbus.Interface(text_proxy, TelepathyGLib.IFACE_CHANNEL)
        text_channel[TelepathyGLib.IFACE_CHANNEL_TYPE_TEXT] = \
            dbus.Interface(text_proxy, TelepathyGLib.IFACE_CHANNEL_TYPE_TEXT)
        text_channel[TelepathyGLib.IFACE_CHANNEL_INTERFACE_GROUP] = \
            dbus.Interface(
                text_proxy, TelepathyGLib.IFACE_CHANNEL_INTERFACE_GROUP)

        self.text_channel = TextChannelWrapper(text_channel, conn)
        self.text_channel.set_received_callback(self._received_cb)
        self.text_channel.handle_pending_messages()
        self.text_channel.set_closed_callback(
            self._one_to_one_connection_closed_cb)
        self._chat_is_room = False
        self._alert(_('On-line'), _('Private chat.'))

        # XXX How do we detect the sender going offline?
        self._entry.set_sensitive(True)
        self.smiley_button.set_sensitive(True)
        self.send_button.set_sensitive(True)
        self._entry.props.placeholder_text = None
        self._entry.grab_focus()

    def _one_to_one_connection_closed_cb(self):
        '''Callback for when the text channel closes.'''
        self._alert(_('Off-line'), _('Left the chat.'))

    def _setup(self):
        self.text_channel = TextChannelWrapper(
            self.shared_activity.telepathy_text_chan,
            self.shared_activity.telepathy_conn)
        self.text_channel.set_received_callback(self._received_cb)
        self._alert(_('On-line'), _('Connected.'))
        self.shared_activity.connect('buddy-joined', self._buddy_joined_cb)
        self.shared_activity.connect('buddy-left', self._buddy_left_cb)
        self._chat_is_room = True
        self._entry.set_sensitive(True)
        self.smiley_button.set_sensitive(True)
        self.send_button.set_sensitive(True)
        self._entry.props.placeholder_text = None
        self._entry.grab_focus()
        self._entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "edit-cancel-black")
        self._entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, 'clear input')
        self._entry.set_icon_activatable(Gtk.EntryIconPosition.SECONDARY, True)
        self._entry.connect('icon-press', self._clear_icon_cb)

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
        for k, v in list(metadata.items()):
            jobject.metadata[k] = v
        file_path = os.path.join(get_activity_root(), 'instance',
                                 '%i_' % time.time())
        open(file_path, 'w').write(url + '\r\n')
        os.chmod(file_path, 0o755)
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
        self._entry_height = style.GRID_CELL_SIZE
        entry_width = int((_get_screen_width()) - \
            2 * (self._entry_height + style.GRID_CELL_SIZE))

        self._entry_grid = Gtk.Grid()
        self._entry_grid.set_size_request(
            int((_get_screen_width()) - 2 * style.GRID_CELL_SIZE),
            self._entry_height)

        self.smiley_button = EventIcon(icon_name='smilies',
                                  pixel_size=self._entry_height)
        self.smiley_gesture = Gtk.GestureClick.new()
        self.smiley_gesture.connect('pressed', lambda g, n, x, y: self._smiley_button_cb(self.smiley_button))
        self.smiley_button.add_controller(self.smiley_gesture)
        self._entry_grid.attach(self.smiley_button, 0, 0, 1, 1)
        self.smiley_button.show()

        self._entry = Gtk.Entry()
        self._entry.set_size_request(entry_width, self._entry_height)

        self._entry.props.placeholder_text = \
            _('You must be connected to a friend before starting to chat.')
        self.focus_ctrl = Gtk.EventControllerFocus.new()
        self.focus_ctrl.connect("enter", lambda c: self._entry_focus_in_cb(self._entry))
        self.focus_ctrl.connect("leave", lambda c: self._entry_focus_out_cb(self._entry))
        self._entry.add_controller(self.focus_ctrl)
        self._entry.connect('activate', self._entry_activate_cb)
        
        self.key_ctrl2 = Gtk.EventControllerKey.new()
        self.key_ctrl2.connect("key-pressed", self._entry_key_press_cb)
        self._entry.add_controller(self.key_ctrl2)
        
        self._entry_grid.attach(self._entry, 1, 0, 1, 1)
        self._entry.show()

        self.send_button = EventIcon(icon_name='send',
                                pixel_size=self._entry_height)
        self.send_gesture = Gtk.GestureClick.new()
        self.send_gesture.connect('pressed', lambda g, n, x, y: self._send_button_cb(self.send_button))
        self.send_button.add_controller(self.send_gesture)
        self._entry_grid.attach(self.send_button, 2, 0, 1, 1)
        self.send_button.show()

        if not self.get_shared():
            self._entry.set_sensitive(False)
            self.smiley_button.set_sensitive(False)
            self.send_button.set_sensitive(False)

        self._chat_width = int(_get_screen_width())
        self._chat_height = int(_get_screen_height() - \
            (self._entry_height + 2 * style.GRID_CELL_SIZE))
        self.chatbox.set_size_request(self._chat_width, self._chat_height)

    def _clear_icon_cb(self, entry, icon_pos):
        self._entry.set_text("")

    def _entry_focus_in_cb(self, entry):
        self._hide_smiley_window()

    def _entry_focus_out_cb(self, entry):
        pass

    def _entry_key_press_cb(self, controller, keyval, keycode, state):
        '''Check for scrolling keys.

        Check if the user pressed Page Up, Page Down, Home or End and
        scroll the window according the pressed key.
        '''
        vadj = self.chatbox.get_vadjustment()
        if keyval == Gdk.KEY_Page_Down:
            value = vadj.get_value() + vadj.page_size
            if value > vadj.upper - vadj.page_size:
                value = vadj.upper - vadj.page_size
            vadj.set_value(value)
        elif keyval == Gdk.KEY_Page_Up:
            vadj.set_value(vadj.get_value() - vadj.page_size)
        elif keyval == Gdk.KEY_Home and \
                state & Gdk.ModifierType.CONTROL_MASK:
            vadj.set_value(vadj.lower)
        elif keyval == Gdk.KEY_End and \
                state & Gdk.ModifierType.CONTROL_MASK:
            vadj.set_value(vadj.upper - vadj.page_size)

    def _smiley_button_cb(self, widget):
        self._show_smiley_window()

    def _send_button_cb(self, widget):
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
        SOUNDS_PATH = os.path.join(get_bundle_path(), 'sounds')
        SOUNDS = {'said_nick': os.path.join(SOUNDS_PATH, 'alert.wav'),
                  'login': os.path.join(SOUNDS_PATH, 'login.wav'),
                      'logout': os.path.join(SOUNDS_PATH, 'logout.wav')}

        self.element.set_state(Gst.State.NULL)
        self.element.set_property('uri', 'file://%s' % SOUNDS[event])
        self.element.set_state(Gst.State.PLAYING)


    def _show_smiley_window(self):
        if not hasattr(self, '_smiley_window'):
            self.busy()
            self._create_smiley_window()
        self._main_stack.set_visible_child_name("smiley_window")

    def _hide_smiley_window(self):
        if hasattr(self, '_smiley_window'):
            self._main_stack.set_visible_child_name("chatbox")


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
        ct = TelepathyGLib.IFACE_CHANNEL_TYPE_TEXT
        m = self._text_chan[ct].connect_to_signal(
            'Received', self._received_cb)
        self._signal_matches.append(m)

    def handle_pending_messages(self):
        '''Get pending messages and show them as received.'''
        ct = TelepathyGLib.IFACE_CHANNEL_TYPE_TEXT
        pm = self._text_chan[ct].ListPendingMessages(False)
        for identity, timestamp, sender, type_, flags, text in pm:
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
                co = TelepathyGLib.IFACE_CONNECTION_INTERFACE_ALIASING
                nick = self._conn[co].RequestAliases([sender])[0]
                buddy = {'nick': nick, 'color': '#000000,#808080'}
            else:
                # Normal sugar4 MUC chat
                # XXX: cache these
                buddy = self._get_buddy(sender)
            self._activity_cb(buddy, text)
            ct = TelepathyGLib.IFACE_CHANNEL_TYPE_TEXT
            self._text_chan[ct].AcknowledgePendingMessages([identity])
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
        conn_proxy = dbus.Bus().get_object(tp_name, tp_path)
        conn = dbus.Interface(conn_proxy, TelepathyGLib.IFACE_CONNECTION)
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


class SmileyToolbar(Gtk.Box):

    def __init__(self, activity):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL)
        self.add_css_class("smiley-toolbar-grey")

        self._activity = activity
        self._add_separator()

        self._icon = Icon(icon_name='smilies-white')
        self._add_widget(self._icon)

        self._add_separator()

        self._title = Gtk.Label(label=_('Insert a smiley'))
        self._add_widget(self._title)

        self._add_separator(True)

        self.cancel_button = ToolButton('dialog-cancel')
        self.cancel_button.set_tooltip(_('Cancel'))
        self.cancel_button.connect('clicked', self.__cancel_button_clicked_cb)
        self.append(self.cancel_button)

    def _add_separator(self, expand=False):
        separator = Gtk.Box()
        if expand:
            separator.set_hexpand(True)
        else:
            separator.set_size_request(style.DEFAULT_SPACING, -1)
        self.append(separator)

    def _add_widget(self, widget, expand=False):
        if expand:
            widget.set_hexpand(True)
        self.append(widget)

    def __cancel_button_clicked_cb(self, widget, data=None):
        self._activity._hide_smiley_window()
