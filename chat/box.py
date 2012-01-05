# Copyright 2007-2008 One Laptop Per Child
# Copyright 2009, Aleksey Lim
# Copyright 2010, Mukesh Gupta
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
import os
import time
import logging
from datetime import datetime
from gettext import gettext as _
from os.path import join

import gtk
import pango
import cairo

from sugar.graphics import style
from sugar.graphics.palette import Palette
from sugar.presence import presenceservice
from sugar.graphics.menuitem import MenuItem
from sugar.activity.activity import get_activity_root, show_object_in_journal
from sugar.util import timestamp_to_elapsed_string
from sugar.datastore import datastore
from sugar import profile

from chat import smilies
from chat.roundbox import RoundBox


_URL_REGEXP = re.compile('((http|ftp)s?://)?'
    '(([-a-zA-Z0-9]+[.])+[-a-zA-Z0-9]{2,}|([0-9]{1,3}[.]){3}[0-9]{1,3})'
    '(:[1-9][0-9]{0,4})?(/[-a-zA-Z0-9/%~@&_+=;:,.?#]*[a-zA-Z0-9/])?')


class ColorLabel(gtk.Label):

    def __init__(self, text, color=None):
        self._color = color
        if self._color is not None:
            text = '<span foreground="%s">' % self._color.get_html() + \
                    text + '</span>'
        gtk.Label.__init__(self)
        self.set_use_markup(True)
        self.set_markup(text)


class LinkLabel(ColorLabel):

    def __init__(self, text, color=None):
        self.text = '<a href="%s">' % text + \
                text + '</a>'
        ColorLabel.__init__(self, self.text, color)

    def create_palette(self):
        return _URLMenu(self.text)


class ChatBox(gtk.ScrolledWindow):

    def __init__(self):
        gtk.ScrolledWindow.__init__(self)

        self.owner = presenceservice.get_instance().get_owner()

        # Auto vs manual scrolling:
        self._scroll_auto = True
        self._scroll_value = 0.0
        self._last_msg_sender = None
        # Track last message, to combine several messages:
        self._last_msg = None
        self._chat_log = ''

        self._conversation = gtk.VBox()
        self._conversation.set_homogeneous(False)
        #self._conversation.background_color=style.COLOR_WHITE
                #spacing=0,
                #box_width=-1,  # natural width
                #background_color=style.COLOR_WHITE.get_int())

        self.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        self.add_with_viewport(self._conversation)
        vadj = self.get_vadjustment()
        vadj.connect('changed', self._scroll_changed_cb)
        vadj.connect('value-changed', self._scroll_value_changed_cb)

    def get_log(self):
        return self._chat_log

    def add_text(self, buddy, text, status_message=False):
        """Display text on screen, with name and colors.

        buddy -- buddy object or dict {nick: string, color: string}
                 (The dict is for loading the chat log from the journal,
                 when we don't have the buddy object any more.)
        text -- string, what the buddy said
        status_message -- boolean
            False: show what buddy said
            True: show what buddy did

        .------------- rb ---------------.
        | +name_vbox+ +----msg_vbox----+ |
        | |         | |                | |
        | | nick:   | | +--msg_hbox--+ | |
        | |         | | | text       | | |
        | +---------+ | +------------+ | |
        |             |                | |
        |             | +--msg_hbox--+ | |
        |             | | text | url | | |
        |             | +------------+ | |
        |             +----------------+ |
        `--------------------------------'
        """
        if not buddy:
            buddy = self.owner

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

        # Select text color based on fill color:
        color_fill_rgba = style.Color(color_fill_html).get_rgba()
        color_fill_gray = (color_fill_rgba[0] + color_fill_rgba[1] +
                color_fill_rgba[2]) / 3
        color_stroke = style.Color(color_stroke_html)
        color_fill = style.Color(color_fill_html)

        if color_fill_gray < 0.5:
            text_color = style.COLOR_WHITE
        else:
            text_color = style.COLOR_BLACK

        self._add_log(nick, color, text, status_message)

        # Check for Right-To-Left languages:
        if pango.find_base_dir(nick, -1) == pango.DIRECTION_RTL:
            lang_rtl = True
        else:
            lang_rtl = False

        # Check if new message box or add text to previous:
        new_msg = True
        if self._last_msg_sender:
            if not status_message:
                if buddy == self._last_msg_sender:
                    # Add text to previous message
                    new_msg = False

        if not new_msg:
            rb = self._last_msg
            msg_vbox = rb.get_children()[1]
            msg_hbox = gtk.HBox()
            msg_hbox.show()
            msg_vbox.pack_start(msg_hbox, True, True)
        else:
            rb = RoundBox()
            rb.background_color = color_fill
            rb.border_color = color_stroke
            self._last_msg = rb
            self._last_msg_sender = buddy

            if not status_message:
                name = ColorLabel(text=nick + ':   ', color=text_color)
                name_vbox = gtk.VBox()
                name_vbox.pack_start(name, False, False)
                rb.pack_start(name_vbox, False, False)
            msg_vbox = gtk.VBox()
            rb.pack_start(msg_vbox, False, False)
            msg_hbox = gtk.HBox()
            msg_vbox.pack_start(msg_hbox, False, False)

        if status_message:
            self._last_msg_sender = None

        match = _URL_REGEXP.search(text)
        while match:
            # there is a URL in the text
            starttext = text[:match.start()]
            if starttext:
                message = ColorLabel(
                    text=starttext,
                    color=text_color)
                msg_hbox.pack_start(message, True, True)
                message.show()
            url = text[match.start():match.end()]

            message = LinkLabel(
                text=url,
                color=text_color)
            message.connect('activate-link', self._link_activated_cb)

            align = gtk.Alignment(xalign=0.0, yalign=0.0, xscale=0.0,
                    yscale=0.0)
            align.add(message)

            msg_hbox.pack_start(align, True, True)
            msg_hbox.show()
            text = text[match.end():]
            match = _URL_REGEXP.search(text)

        if text:
            for word in smilies.parse(text):
                if isinstance(word, cairo.ImageSurface):
                    pass
                    # TODO:
                    """
                    item = hippo.CanvasImage(
                            image=word,
                            border=0,
                            border_color=style.COLOR_BUTTON_GREY.get_int(),
                            xalign=hippo.ALIGNMENT_CENTER,
                            yalign=hippo.ALIGNMENT_CENTER)
                    """
                else:
                    item = ColorLabel(
                            text=word,
                            color=text_color)
                    item.show()
                align = gtk.Alignment(xalign=0.0, yalign=0.0, xscale=0.0,
                        yscale=0.0)
                align.add(item)
                msg_hbox.pack_start(align, True, True)

        # Order of boxes for RTL languages:
        if lang_rtl:
            msg_hbox.reverse()
            if new_msg:
                rb.reverse()

        if new_msg:
            box = RoundBox()  # TODO: padding=2)
            box.show()
            box.pack_start(rb, True, True)
            self._conversation.pack_start(box, False, False)
        self._conversation.show_all()

    def add_separator(self, timestamp):
        """Add whitespace and timestamp between chat sessions."""
        time_with_current_year = (time.localtime(time.time())[0],) +\
                time.strptime(timestamp, "%b %d %H:%M:%S")[1:]

        timestamp_seconds = time.mktime(time_with_current_year)
        if timestamp_seconds > time.time():
            time_with_previous_year = (time.localtime(time.time())[0] - 1,) +\
                    time.strptime(timestamp, "%b %d %H:%M:%S")[1:]
            timestamp_seconds = time.mktime(time_with_previous_year)

        message = ColorLabel(
            text=timestamp_to_elapsed_string(timestamp_seconds),
            color=style.COLOR_BUTTON_GREY)

        box = gtk.HBox()
        box.show()
        align = gtk.Alignment(xalign=0.5, yalign=0.0, xscale=0.0, yscale=0.0)
        box.pack_start(align, True, True)
        align.add(message)
        box.show_all()
        self._conversation.pack_start(box, False, False)
        self.add_log_timestamp(timestamp)

        self._last_msg_sender = None

    def add_log_timestamp(self, existing_timestamp=None):
        """Add a timestamp entry to the chat log."""
        if existing_timestamp is not None:
            self._chat_log += '%s\t\t\n' % existing_timestamp
        else:
            self._chat_log += '%s\t\t\n' % (
                datetime.strftime(datetime.now(), '%b %d %H:%M:%S'))

    def _add_log(self, nick, color, text, status_message):
        """Add the text to the chat log.

        nick -- string, buddy nickname
        color -- string, buddy.props.color
        text -- string, body of message
        status_message -- boolean
        """
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
        """Turn auto scrolling on or off.

        If the user scrolled up, turn it off.
        If the user scrolled to the bottom, turn it back on.
        """
        if adj.get_value() < self._scroll_value:
            self._scroll_auto = False
        elif adj.get_value() == adj.upper - adj.page_size:
            self._scroll_auto = True

    def _scroll_changed_cb(self, adj, scroll=None):
        """Scroll the chat window to the bottom"""
        if self._scroll_auto:
            adj.set_value(adj.upper - adj.page_size)
            self._scroll_value = adj.get_value()

    def _link_activated_cb(self, label, link):
        url = _url_check_protocol(link.props.text)
        self._show_via_journal(url)
        return False

    def _show_via_journal(self, url):
        """Ask the journal to display a URL"""
        logging.debug('Create journal entry for URL: %s', url)
        jobject = datastore.create()
        metadata = {
            'title': "%s: %s" % (_('URL from Chat'), url),
            'title_set_by_user': '1',
            'icon-color': profile.get_color().to_string(),
            'mime_type': 'text/uri-list',
            }
        for k, v in metadata.items():
            jobject.metadata[k] = v
        file_path = join(get_activity_root(), 'instance', '%i_' % time.time())
        open(file_path, 'w').write(url + '\r\n')
        os.chmod(file_path, 0755)
        jobject.set_file_path(file_path)
        datastore.write(jobject)
        show_object_in_journal(jobject.object_id)
        jobject.destroy()
        os.unlink(file_path)


class _URLMenu(Palette):

    def __init__(self, url):
        Palette.__init__(self, url)

        self.owns_clipboard = False
        self.url = _url_check_protocol(url)

        menu_item = MenuItem(_('Copy to Clipboard'), 'edit-copy')
        menu_item.connect('activate', self._copy_to_clipboard_cb)
        self.menu.append(menu_item)
        menu_item.show()

    def create_palette(self):
        pass

    def _copy_to_clipboard_cb(self, menuitem):
        logging.debug('Copy %s to clipboard', self.url)
        clipboard = gtk.clipboard_get()
        targets = [("text/uri-list", 0, 0),
                   ("UTF8_STRING", 0, 1)]

        if not clipboard.set_with_data(targets,
                                       self._clipboard_data_get_cb,
                                       self._clipboard_clear_cb,
                                       (self.url)):
            logging.error('GtkClipboard.set_with_data failed!')
        else:
            self.owns_clipboard = True

    def _clipboard_data_get_cb(self, clipboard, selection, info, data):
        logging.debug('_clipboard_data_get_cb data=%s target=%s', data,
                     selection.target)
        if selection.target in ['text/uri-list']:
            if not selection.set_uris([data]):
                logging.debug('failed to set_uris')
        else:
            logging.debug('not uri')
            if not selection.set_text(data):
                logging.debug('failed to set_text')

    def _clipboard_clear_cb(self, clipboard, data):
        logging.debug('clipboard_clear_cb')
        self.owns_clipboard = False


def _url_check_protocol(url):
    """Check that the url has a protocol, otherwise prepend https://

    url -- string

    Returns url -- string
    """
    protocols = ['http://', 'https://', 'ftp://', 'ftps://']
    no_protocol = True
    for protocol in protocols:
        if url.startswith(protocol):
            no_protocol = False
    if no_protocol:
        url = 'http://' + url
    return url
