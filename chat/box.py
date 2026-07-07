# Copyright 2007-2008 One Laptop Per Child
# Copyright 2009, Aleksey Lim
# Copyright 2010, Mukesh Gupta
# Copyright 2014, Walter Bender
# Copyright 2014, Gonzalo Odiard
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

import re
import time
import logging
from datetime import datetime
from gettext import gettext as _

from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Pango
from gi.repository import GLib

import weakref

_TEXTURE_CACHE = weakref.WeakKeyDictionary()
_CSS_PROVIDER_CACHE = {}
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

def _get_screen_width():
    display = Gdk.Display.get_default()
    if not display:
        return 1200
    monitors = display.get_monitors()
    if monitors.get_n_items() == 0:
        return 1200
    return monitors.get_item(0).get_geometry().width

def _get_screen_height():
    display = Gdk.Display.get_default()
    if not display:
        return 900
    monitors = display.get_monitors()
    if monitors.get_n_items() == 0:
        return 900
    return monitors.get_item(0).get_geometry().height



from sugar4.graphics import style
from sugar4.graphics.palette import Palette, Invoker
from sugar4.graphics.palettemenu import PaletteMenuItem
from sugar4.graphics.palette import MouseSpeedDetector
from sugar4.util import timestamp_to_elapsed_string
from sugar4 import profile

from chat import smilies
from chat.roundbox import RoundBox


_URL_REGEXP = re.compile(
    '((http|ftp)s?://)?'
    '(([-a-zA-Z0-9]+[.])+[-a-zA-Z0-9]{2,}|([0-9]{1,3}[.]){3}[0-9]{1,3})'
    '(:[1-9][0-9]{0,4})?(/[-a-zA-Z0-9/%~@&_+=;:,.?#]*[a-zA-Z0-9/])?')


def _luminance(color):
    ''' Calculate luminance value '''
    return int(color[1:3], 16) * 0.3 + int(color[3:5], 16) * 0.6 + \
        int(color[5:7], 16) * 0.1


def is_low_contrast(colors):
    ''' We require lots of luminance contrast to make color text legible. '''
    # To turn off color on color, always return False
    return _luminance(colors[0]) - _luminance(colors[1]) < 96


def is_dark_too_light(color):
    return _luminance(color) > 96


def lighter_color(colors):
    ''' Which color is lighter? Use that one for the text nick color '''
    if _luminance(colors[0]) > _luminance(colors[1]):
        return 0
    return 1


def darker_color(colors):
    ''' Which color is darker? Use that one for the text background '''
    return 1 - lighter_color(colors)


class TextBox(Gtk.TextView):

    __gsignals__ = {
        'open-on-journal': (GObject.SignalFlags.RUN_FIRST, None, ([str])), }

    def __init__(self, parent,
                 name_color, text_color, bg_color, highlight_color,
                 lang_rtl, nick_name=None, text=None):
        Gtk.TextView.__init__(self)
        self._parent = parent
        self._buffer = Gtk.TextBuffer()
        self._empty_buffer = Gtk.TextBuffer()
        self._empty_buffer.set_text('')
        self._empty = True
        self._name_tag = self._buffer.create_tag(
            'name', foreground=name_color.get_html(), weight=Pango.Weight.BOLD)
        self._fg_tag = self._buffer.create_tag(
            'foreground_color', foreground=text_color.get_html())
        self._subscript_tag = self._buffer.create_tag(
            'subscript', foreground=text_color.get_html(),
            rise=-7 * Pango.SCALE)  # in pixels

        # Initialise each TextView object with a default set of pattern tags
        self._pattern_tag_hilite = self._buffer.create_tag(
            'pattern-hilite', background=style.Color('#D80A0A').get_html())
        self._pattern_tag_select = self._buffer.create_tag(
            'pattern-select', background=style.Color('#09C3F7').get_html())
        if nick_name:
            self._add_name(nick_name)
            self.add_text(text, newline=False)
        elif text:
            self.add_text(text)

        self.resize_box()

        self._lang_rtl = lang_rtl
        self.set_editable(False)
        self.set_cursor_visible(False)
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)

        self.palette = None
        self._deferred_resize_id = None
        self.hand_cursor = Gdk.Cursor.new_from_name("pointer", None)

        self._mouse_detector = MouseSpeedDetector(200, 5)
        self._mouse_detector.connect('motion-slow', self.__mouse_slow_cb)

        highlight_html = highlight_color.get_html()
        bg_html = bg_color.get_html()
        
        # Validate hex colors to prevent CSS injection
        if not _HEX_COLOR_RE.match(highlight_html): highlight_html = '#888888'
        if not _HEX_COLOR_RE.match(bg_html): bg_html = '#FFFFFF'

        cache_key = (bg_html, highlight_html)
        css_provider = _CSS_PROVIDER_CACHE.get(cache_key)
        if css_provider is None:
            css = ('textview, textview text { background-color: transparent; }'
                   'textview text selection { background-color: %s; }'
                   % (highlight_html))
            css_provider = Gtk.CssProvider()
            css_provider.load_from_data(css.encode('utf-8'))
            _CSS_PROVIDER_CACHE[cache_key] = css_provider

        self.get_style_context().add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        click_controller = Gtk.GestureClick()
        click_controller.set_button(0)  # listen to all buttons
        click_controller.connect('pressed', self.__click_pressed_cb)
        click_controller.connect('released', self.__click_released_cb)
        self.add_controller(click_controller)

        motion_controller = Gtk.EventControllerMotion()
        motion_controller.connect('motion', self.__motion_cb)
        motion_controller.connect('leave', self.__leave_cb)
        self.add_controller(motion_controller)

    def do_size_allocate(self, width, height, baseline):
        ''' Load buffer after resize to circumvent race condition '''
        Gtk.TextView.do_size_allocate(self, width, height, baseline)
        if self._deferred_resize_id is None:
            self._deferred_resize_id = GLib.idle_add(
                TextBox._deferred_resize_cb, weakref.ref(self))

    @staticmethod
    def _deferred_resize_cb(self_ref):
        self = self_ref()
        if self is None or not self.get_root():
            return GLib.SOURCE_REMOVE
        self._deferred_resize_id = None
        self.set_buffer(self._buffer)
        if hasattr(self, '_parent') and self._parent is not None:
            self._parent.resize_rb()
        return GLib.SOURCE_REMOVE

    def resize_box(self):
        self.set_buffer(self._empty_buffer)
        self.set_size_request(_get_screen_width() - style.GRID_CELL_SIZE -
                              2 * style.DEFAULT_SPACING, -1)

    def __leave_cb(self, controller):
        self._mouse_detector.stop()

    def __click_pressed_cb(self, gesture, n_press, x, y):
        button = gesture.get_current_button()
        if button == 2:
            return  # Ignore middle click for URLs
            
        if button == 3:
            # To disable the standard textview popup
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            
            bx, by = self.window_to_buffer_coords(Gtk.TextWindowType.WIDGET,
                                                  int(x), int(y))
            found, iter_tags = self.get_iter_at_location(bx, by)

            if not found:
                return

            for tag in iter_tags.get_tags():
                try:
                    url = tag.url
                except AttributeError:
                    url = None
                if url is not None:
                    palette = tag.palette
                    # Pass the click coordinates so the popover positions correctly
                    palette.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=8, height=8))
                    palette.popup()
                    break

    # Links can be activated by clicking.
    def __click_released_cb(self, gesture, n_press, x, y):
        button = gesture.get_current_button()
        if button in (2, 3):
            return
            
        bx, by = self.window_to_buffer_coords(Gtk.TextWindowType.WIDGET,
                                              int(x), int(y))
        found, iter_tags = self.get_iter_at_location(bx, by)

        if not found:
            return

        for tag in iter_tags.get_tags():
            try:
                url = tag.url
            except AttributeError:
                url = None
            if url is not None:
                self._show_via_journal(url)
                break

    def _show_via_journal(self, url):
        self.emit('open-on-journal', url)

    def check_url_hovering(self, x, y):
        # Looks at all tags covering the position (x, y) in the text view,
        # and if one of them is a link return True

        # When check on_slow_mouse event, the position can be out
        # of the widget and return negative values.
        if x < 0 or y < 0:
            return False

        self.palette = None
        found, iter_tags = self.get_iter_at_location(x, y)

        if not found:
            return False

        tags = iter_tags.get_tags()
        for tag in tags:
            try:
                url = tag.url
                self.palette = tag.palette
            except AttributeError:
                url = None
            if url is not None:
                return True
        return False

    def set_cursor_if_appropriate(self, x, y):
        # Looks at all tags covering the position (x, y) in the text view,
        # and if one of them is a link, change the cursor to the 'hands' cursor

        hovering_over_link = self.check_url_hovering(x, y)
        if hovering_over_link:
            self.set_cursor(self.hand_cursor)
            self._mouse_detector.start()
        else:
            self.set_cursor(None)
            self._mouse_detector.stop()

    def __mouse_slow_cb(self, widget):
        if hasattr(self, '_last_mouse_x'):
            hovering_over_link = self.check_url_hovering(
                self._last_mouse_x, self._last_mouse_y)
            if hovering_over_link:
                if self.palette is not None:
                    # Pass the widget coordinates to ensure correct positioning
                    self.palette.set_pointing_to(Gdk.Rectangle(
                        x=self._last_widget_x, y=self._last_widget_y, width=8, height=8))
                    self.palette.popup()
                    self._mouse_detector.stop()
            else:
                if self.palette is not None:
                    self.palette.popdown()

    # Update the cursor image if the pointer moved.
    def __motion_cb(self, controller, x, y):
        bx, by = self.window_to_buffer_coords(Gtk.TextWindowType.WIDGET,
                                              int(x), int(y))
        self._last_mouse_x = bx
        self._last_mouse_y = by
        self._last_widget_x = int(x)
        self._last_widget_y = int(y)
        self.set_cursor_if_appropriate(bx, by)

    def _add_name(self, name):
        buf = self._buffer
        self.iter_text = self._buffer.get_iter_at_offset(0)
        words = name.split()
        for word in words:
            buf.insert_with_tags(self.iter_text, word, self._name_tag)
            buf.insert_with_tags(self.iter_text, ' ', self._fg_tag)

        self._empty = False

    def add_text(self, text, newline=True):
        buf = self._buffer
        self.iter_text = self._buffer.get_end_iter()

        if not self._empty:
            if newline:
                buf.insert(self.iter_text, '\n')
            else:
                buf.insert(self.iter_text, ' ')

        words = text.split()
        for word in words:
            if _URL_REGEXP.match(word) is not None:
                tag = buf.create_tag(None, underline=Pango.Underline.SINGLE)
                tag.url = word
                palette = _URLMenu(word)
                # FIXME: TypeError: _URLMenu: unknown signal name:
                # enter-notify-event - leave-notify-event
                # palette.connect('enter-notify-event',
                #                 self.__palette_mouse_enter_cb)
                # palette.connect('leave-notify-event',
                #                 self.__palette_mouse_leave_cb)
                tag.palette = palette
                buf.insert_with_tags(self.iter_text, word, tag, self._fg_tag)
            else:
                for i in smilies.parse(word):
                    if isinstance(i, GdkPixbuf.Pixbuf):
                        start = self.iter_text.get_offset()
                        
                        texture = _TEXTURE_CACHE.get(i)
                        if texture is None:
                            texture = Gdk.Texture.new_for_pixbuf(i)
                            _TEXTURE_CACHE[i] = texture
                            
                        buf.insert_paintable(self.iter_text, texture)
                        buf.apply_tag(self._subscript_tag,
                                      buf.get_iter_at_offset(start),
                                      self.iter_text)
                    else:
                        buf.insert_with_tags(self.iter_text, i, self._fg_tag)
            buf.insert_with_tags(self.iter_text, ' ', self._fg_tag)

        self._empty = False

    def get_buffer(self):
        return self._buffer


class ChatBox(Gtk.ScrolledWindow):

    __gsignals__ = {
        'open-on-journal': (GObject.SignalFlags.RUN_FIRST, None, ([str])),
        'new-message': (GObject.SignalFlags.RUN_FIRST, None, ([]))
    }

    def __init__(self, owner):
        Gtk.ScrolledWindow.__init__(self)

        self._owner = owner

        # Auto vs manual scrolling:
        self._scroll_auto = True
        self._scroll_value = 0.0
        self._last_msg_sender = None
        # Track last message, to combine several messages:
        self._last_msg = None
        self._chat_log = ''
        self._row_counter = 0

        # We need access to individual messages for resizing
        # TODO: use a signal for this
        self._rb_list = []
        self._grid_list = []
        self._message_list = []

        self._conversation = Gtk.Grid()
        self._conversation.set_row_spacing(style.DEFAULT_PADDING)
        self._conversation.set_margin_start(0)
        self._conversation.set_margin_end(0)
        self._conversation.set_margin_top(0)
        self._conversation.set_margin_bottom(0)
        self._conversation.set_size_request(
            _get_screen_width() - style.GRID_CELL_SIZE, -1)

        self.search_text = ''

        # A TextMark start object, a TextMark end object and block index number
        self.highlight_text = (None, None, None)

        # OSK padding for conversation
        self._dy = 0

        evbox = Gtk.Box()
        evbox.set_hexpand(True)
        evbox.add_css_class("view")

        evbox.append(self._conversation)

        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
        self.set_child(evbox)

        vadj = self.get_vadjustment()
        vadj.connect('changed', self._scroll_changed_cb)
        vadj.connect('value-changed', self._scroll_value_changed_cb)

    def set_search_text(self, text):
        self.search_text = text
        count = 0
        for textbox_count in range(0, len(self._message_list)):
            _buffer = self._message_list[textbox_count].get_buffer()
            start, end = _buffer.get_bounds()
            _buffer.remove_tag_by_name('pattern-hilite', start, end)
            _buffer.remove_tag_by_name('pattern-select', start, end)

            text_iter = _buffer.get_start_iter()

            if self.search_text != '':
                while True:
                    next_found = text_iter.forward_search(
                        self.search_text,
                        Gtk.TextSearchFlags.VISIBLE_ONLY |
                        Gtk.TextSearchFlags.TEXT_ONLY,
                        None)
                    if next_found is None:
                        break
                    count += 1
                    start, end = next_found
                    if count == 1 and self.highlight_text[2] is None:
                        # Create marks
                        start_mark = \
                            _buffer.create_mark('start', start,
                                                left_gravity=True)
                        end_mark = \
                            _buffer.create_mark('end', end,
                                                left_gravity=True)
                        self.highlight_text = \
                            (start_mark, end_mark, textbox_count)
                        _buffer.apply_tag_by_name('pattern-select', start, end)
                    _buffer.apply_tag_by_name('pattern-hilite', start, end)
                    text_iter = end

    def check_next(self, direction):
        current_index = self.highlight_text[2]
        if current_index is not None:
            if direction == 'forward':
                for i in range(current_index, len(self._message_list)):
                    _buffer = self._message_list[i].get_buffer()
                    if i == current_index:
                        # End iter
                        text_iter = \
                            _buffer.get_iter_at_mark(
                                self.highlight_text[1])
                    else:
                        text_iter = _buffer.get_start_iter()
                    next_exists = \
                        text_iter.forward_to_tag_toggle(
                            self._message_list[i]._pattern_tag_hilite)
                    if next_exists:
                        return True
                return False
            elif direction == 'backward':
                for i in range(current_index, -1, -1):
                    _buffer = self._message_list[i].get_buffer()
                    if i == current_index:
                        # Start iter
                        text_iter = \
                            _buffer.get_iter_at_mark(
                                self.highlight_text[0])
                    else:
                        text_iter = _buffer.get_end_iter()
                    prev_exists = \
                        text_iter.backward_to_tag_toggle(
                            self._message_list[i]._pattern_tag_hilite)
                    if prev_exists:
                        return True
                return False
            else:
                return False

    def get_next_result(self, direction):
        current_index = self.highlight_text[2]
        if current_index is not None:
            if direction == 'forward':
                for i in range(current_index, len(self._message_list)):
                    _buffer = self._message_list[i].get_buffer()
                    if i == current_index:
                        # End iter
                        text_iter = \
                            _buffer.get_iter_at_mark(self.highlight_text[1])
                    else:
                        text_iter = _buffer.get_start_iter()

                    _temp = text_iter \
                        .forward_search(self.search_text,
                                        Gtk.TextSearchFlags.VISIBLE_ONLY |
                                        Gtk.TextSearchFlags.TEXT_ONLY,
                                        None)
                    if _temp is not None:
                        start, end = _temp
                        if i == current_index:
                            _buffer.move_mark_by_name('start', start)
                            _buffer.move_mark_by_name('end', end)
                        else:
                            start_mark = _buffer.create_mark('start', start,
                                                             left_gravity=True)
                            end_mark = _buffer.create_mark('end', end,
                                                           left_gravity=True)
                            self.highlight_text = \
                                (start_mark, end_mark, i)
                        return _temp
                    else:
                        if i == current_index:
                            _buffer.delete_mark_by_name('start')
                            _buffer.delete_mark_by_name('end')
                return None
            elif direction == 'backward':
                for i in range(current_index, -1, -1):
                    _buffer = self._message_list[i].get_buffer()
                    if i == current_index:
                        # Start iter
                        text_iter = \
                            _buffer.get_iter_at_mark(
                                self.highlight_text[0])
                    else:
                        text_iter = _buffer.get_end_iter()

                    _temp = text_iter \
                        .backward_search(self.search_text,
                                         Gtk.TextSearchFlags.VISIBLE_ONLY |
                                         Gtk.TextSearchFlags.TEXT_ONLY,
                                         None)
                    if _temp is not None:
                        start, end = _temp
                        if i == current_index:
                            _buffer.move_mark_by_name('start', start)
                            _buffer.move_mark_by_name('end', end)
                        else:
                            start_mark = _buffer.create_mark('start', start,
                                                             left_gravity=True)
                            end_mark = \
                                _buffer.create_mark('end', end,
                                                    left_gravity=True)
                            self.highlight_text = \
                                (start_mark, end_mark, i)
                        return _temp
                    else:
                        if i == current_index:
                            _buffer.delete_mark_by_name('start')
                            _buffer.delete_mark_by_name('end')
                return None
        else:
            return None

    def search(self, direction):
        next_found = self.get_next_result(direction)
        if next_found:
            current_search_index = self.highlight_text[2]
            _buffer = \
                self._message_list[current_search_index].get_buffer()

            for count in range(0, len(self._message_list)):
                temp_buf = self._message_list[count].get_buffer()
                t_start, t_end = temp_buf.get_bounds()
                temp_buf.remove_tag_by_name('pattern-select', t_start, t_end)

            start, end = next_found
            _buffer.apply_tag_by_name('pattern-select', start, end)
            _buffer.place_cursor(start)

            self._message_list[current_search_index] \
                .scroll_to_iter(start, 0.1, use_align=False,
                                xalign=0.0, yalign=0.0)
            self._message_list[current_search_index] \
                .scroll_to_iter(end, 0.1, use_align=False,
                                xalign=0.0, yalign=0.0)

    def get_textbox(self, textbox_count):
        return self._message_list[textbox_count]

    def number_of_textboxes(self):
        return len(self._message_list)

    def __open_on_journal(self, widget, url):
        self.emit('open-on-journal', url)

    def get_log(self):
        return self._chat_log

    def add_text(self, buddy, text, status_message=False):
        r'''Display text on screen, with name and colors.
        buddy -- buddy object or dict {nick: string, color: string}
        (The dict is for loading the chat log from the journal,
        when we don't have the buddy object any more.)
        text -- string, what the buddy said
        status_message -- boolean
        False: show what buddy said
        True: show what buddy did

        .----- rb ------------.
        |  +----align-------+ |
        |  | +--message---+ | |
        |  | | nick:      | | |
        |  | | text 1     | | |
        |  | | text 2     | | |
        |  | +------------+ | |
        |  +----------------+ |
        `----------------- +--'
                          \|

        The color scheme for owner messages is:
        nick in lighter of stroke and fill colors
        background in darker of stroke and fill colors
        text in white

        The color scheme for buddy messages is:
        nick in darker of stroke and fill colors
        background in light gray
        text in black

        rb has a tail on the right for owner messages and the left for
        buddy messages.
        '''
        if not buddy:
            buddy = self._owner

        if type(buddy) is dict:
            # dict required for loading chat log from journal
            nick = buddy['nick']
            color = buddy['color']
        else:
            nick = buddy.props.nick
            color = buddy.props.color
        try:
            color_stroke_html, color_fill_html = color.split(',')
        except ValueError:
            color_stroke_html, color_fill_html = ('#000000', '#888888')

        lighter = lighter_color(color.split(','))
        darker = 1 - lighter

        if len(text) > 3 and text[0:4] == '/me ':
            me_message = True
        else:
            me_message = False

        if status_message or me_message:
            text_color = style.COLOR_WHITE
            nick_color = style.COLOR_WHITE
            color_fill = style.Color('#808080')
            highlight_fill = style.COLOR_WHITE
            tail = None
        else:
            highlight_fill = style.COLOR_BUTTON_GREY
            if is_dark_too_light(color.split(',')[darker]):
                text_color = style.COLOR_BLACK
                darker = lighter  # use black on lighter of the two colors
            else:
                text_color = style.COLOR_WHITE
            if darker == 0:
                color_fill = style.Color(color_stroke_html)
                if is_low_contrast(color.split(',')):
                    nick_color = text_color
                else:
                    nick_color = style.Color(color_fill_html)
            else:
                color_fill = style.Color(color_fill_html)
                if is_low_contrast(color.split(',')):
                    nick_color = text_color
                else:
                    nick_color = style.Color(color_stroke_html)
            if nick == profile.get_nick_name():
                tail = 'right'
            else:
                tail = 'left'

        color_stroke = None

        self._add_log(nick, color, text, status_message)

        # Check for Right-To-Left languages:
        if Pango.find_base_dir(nick, -1) == Pango.Direction.RTL:
            lang_rtl = True
        else:
            lang_rtl = False

        # Check if new message box or add text to previous:
        new_msg = True
        if self._last_msg_sender and buddy == self._last_msg_sender:
            # Add text to previous message
            if not (me_message or status_message):
                new_msg = False

        if not new_msg:
            message = self._last_msg
            message.add_text(text)
        else:
            rb = RoundBox()
            rb.background_color = color_fill
            rb.border_color = color_stroke
            rb.tail = tail
            self._rb_list.append(rb)

            grid_internal = Gtk.Grid()
            grid_internal.set_row_spacing(0)
            grid_internal.set_hexpand(True)
            grid_internal.set_margin_start(style.DEFAULT_PADDING)
            grid_internal.set_margin_end(style.DEFAULT_PADDING)
            grid_internal.set_margin_top(style.DEFAULT_PADDING)
            grid_internal.set_margin_bottom(style.DEFAULT_PADDING)
            grid_internal.set_size_request(
                _get_screen_width() - style.GRID_CELL_SIZE, -1)
            self._grid_list.append(grid_internal)

            row = 0

            if status_message:
                nick = None
            elif me_message:
                text = text[4:]

            message = TextBox(self, nick_color, text_color, color_fill,
                              highlight_fill, lang_rtl, nick, text)
            self._message_list.append(message)
            message.connect('open-on-journal', self.__open_on_journal)

            self._last_msg_sender = buddy
            self._last_msg = message

            grid_internal.attach(message, 0, row, 1, 1)

            align_box = Gtk.Box()
            align_box.set_hexpand(True)
            align_box.set_valign(Gtk.Align.START)
            if rb.tail is None:
                bottom_padding = style.zoom(7)
            else:
                bottom_padding = style.zoom(35)
            align_box.set_margin_top(style.zoom(7))
            align_box.set_margin_bottom(bottom_padding)
            align_box.set_margin_start(style.zoom(30))
            align_box.set_margin_end(style.zoom(30))
            
            align_box.append(grid_internal)
            rb.append(align_box)
            
            self._conversation.attach(rb, 0, self._row_counter, 1, 1)
            self._row_counter += 1

        if status_message:
            self._last_msg_sender = None

        self.emit("new-message")

    def add_separator(self, timestamp):
        '''Add whitespace and timestamp between chat sessions.'''
        time_with_current_year = \
            (time.localtime(time.time())[0], ) + \
            time.strptime(timestamp, '%b %d %H:%M:%S')[1:]

        timestamp_seconds = time.mktime(time_with_current_year)
        if timestamp_seconds > time.time():
            time_with_previous_year = \
                (time.localtime(time.time())[0] - 1, ) + \
                time.strptime(timestamp, '%b %d %H:%M:%S')[1:]
            timestamp_seconds = time.mktime(time_with_previous_year)

        message = TextBox(self,
                          style.COLOR_BUTTON_GREY, style.COLOR_BUTTON_GREY,
                          style.COLOR_WHITE, style.COLOR_BUTTON_GREY, False,
                          None, timestamp_to_elapsed_string(timestamp_seconds))
        self._message_list.append(message)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        message.set_halign(Gtk.Align.CENTER)
        message.set_valign(Gtk.Align.START)
        message.set_hexpand(False)
        box.append(message)
        self._conversation.attach(box, 0, self._row_counter, 1, 1)
        self._row_counter += 1
        self.add_log_timestamp(timestamp)
        self._last_msg_sender = None

    def add_log_timestamp(self, existing_timestamp=None):
        '''Add a timestamp entry to the chat log.'''
        if existing_timestamp is not None:
            self._chat_log += '%s\t\t\n' % existing_timestamp
        else:
            self._chat_log += '%s\t\t\n' % (
                datetime.strftime(datetime.now(), '%b %d %H:%M:%S'))

    def _add_log(self, nick, color, text, status_message):
        '''Add the text to the chat log.
        nick -- string, buddy nickname
        color -- string, buddy.props.color
        text -- string, body of message
        status_message -- boolean
        '''
        if not nick:
            nick = '???'
        if not color:
            color = '#000000,#FFFFFF'
        if not text:
            text = '-'
        if not status_message:
            status_message = False
        self._chat_log += '%s\t%s\t%s\t%d\t%s\n' % (
            datetime.strftime(datetime.now(), '%b %d %H:%M:%S'),
            nick, color, status_message, text)

    def _scroll_value_changed_cb(self, adj, scroll=None):
        '''Turn auto scrolling on or off.
        If the user scrolled up, turn it off.
        If the user scrolled to the bottom, turn it back on.
        '''
        if adj.get_value() < self._scroll_value:
            self._scroll_auto = False
        elif adj.get_value() == adj.get_upper() - adj.get_page_size():
            self._scroll_auto = True

    def _scroll_changed_cb(self, adj, scroll=None):
        '''Scroll the chat window to the bottom'''
        if self._scroll_auto:
            adj.set_value(adj.get_upper() - adj.get_page_size())
            self._scroll_value = adj.get_value()

    def resize_all(self):
        for message in self._message_list:
            message.resize_box()
        self.resize_rb()

    def resize_rb(self):
        for grid in self._grid_list:
            grid.set_size_request(
                _get_screen_width() - style.GRID_CELL_SIZE, -1)
        for rb in self._rb_list:
            rb.set_size_request(
                _get_screen_width() - style.GRID_CELL_SIZE, -1)
        self.resize_conversation()

    def resize_conversation(self, dy=None):
        ''' Take into account OSK (dy) '''
        if dy is None:
            dy = self._dy
        else:
            self._dy = dy

        self._conversation.set_margin_bottom(dy)
        self._conversation.set_size_request(
            _get_screen_width() - style.GRID_CELL_SIZE, -1)


class ContentInvoker(Invoker):
    def __init__(self):
        Invoker.__init__(self)
        self._position_hint = self.AT_CURSOR

    def get_default_position(self):
        return self.AT_CURSOR

    def get_toplevel(self):
        return None


class _URLMenu(Palette):

    def __init__(self, url):
        Palette.__init__(self, url)
        self.url = self._url_check_protocol(url)

        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        menu_box.set_margin_start(1)
        menu_box.set_margin_end(1)
        menu_box.set_margin_top(1)
        menu_box.set_margin_bottom(1)
        
        menu_item = PaletteMenuItem(_('Copy to Clipboard'), 'edit-copy')
        menu_item.connect('activate', self._copy_to_clipboard_cb)
        menu_box.append(menu_item)
        
        self.set_content(menu_box)
        self.props.invoker = ContentInvoker()

    def create_palette(self):
        pass

    def _copy_to_clipboard_cb(self, menuitem):
        logging.debug('Copy %s to clipboard', self.url)
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set_text(self.url)

    def _url_check_protocol(self, url):
        '''Check that the url has a protocol, otherwise prepend https://
        url -- string
        Returns url -- string
        '''
        protocols = ['http://', 'https://', 'ftp://', 'ftps://']
        no_protocol = True
        for protocol in protocols:
            if url.startswith(protocol):
                no_protocol = False
        if no_protocol:
            url = 'http://' + url
        return url
