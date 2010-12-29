# Copyright 2007-2008 One Laptop Per Child
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
import hippo
import cairo
import gtk
import pango
import logging
import re
import cjson
import time
import os
import sugar
import glob
import rsvg
import math
from os.path import join, basename, exists



from datetime import datetime
from activity import ViewSourceActivity
from sugar.activity.activity import Activity, ActivityToolbox, SCOPE_PRIVATE
from sugar.graphics import style
from sugar.activity.activity import get_activity_root
from sugar.graphics.alert import NotifyAlert
from sugar.graphics.style import (Color, COLOR_BLACK, COLOR_WHITE, 
    COLOR_BUTTON_GREY, FONT_BOLD, FONT_NORMAL)
from sugar.graphics.roundbox import CanvasRoundBox
from sugar.graphics import style
from sugar.graphics.xocolor import XoColor
from sugar.graphics.palette import Palette, CanvasInvoker
from sugar.graphics.menuitem import MenuItem
from sugar.util import timestamp_to_elapsed_string
from sugar.graphics.toolbarbox import ToolbarBox
from sugar.activity.widgets import *
from sugar.presence import presenceservice
from telepathy.client import Connection, Channel
from telepathy.interfaces import (
    CHANNEL_INTERFACE, CHANNEL_INTERFACE_GROUP, CHANNEL_TYPE_TEXT,
    CONN_INTERFACE_ALIASING)
from telepathy.constants import (
    CHANNEL_GROUP_FLAG_CHANNEL_SPECIFIC_HANDLES,
    CHANNEL_TEXT_MESSAGE_TYPE_NORMAL)

logger = logging.getLogger('chat-activity')

URL_REGEXP = re.compile('((http|ftp)s?://)?'
    '(([-a-zA-Z0-9]+[.])+[-a-zA-Z0-9]{2,}|([0-9]{1,3}[.]){3}[0-9]{1,3})'
    '(:[1-9][0-9]{0,4})?(/[-a-zA-Z0-9/%~@&_+=;:,.?#]*[a-zA-Z0-9/])?')

TEMP_SVG_PATH="icons/smilies"
ICON_SVG_PATH=os.path.join(get_activity_root(),'data', 'icons','smilies')

## For adding a new smiley add an entry in this dictionary and place the corresponding smiley file in data/icons
SMILIES = [
        ('smile', _('Smile'), [':)', ':-)']),
        ('wink', _('Winking'), [';)', ';-)']),
        ('sad', _('Sad'), [':-(', ':(']),
        ('grin', _('Grin'), [':D', ':-D']),
        ('shock', _('Shock'), [':O', ':-O', '=-O', '=O']),
        ('cool', _('Cool'), ['B)', 'B-)', '8-)', '8)']),
        ('tongue', _('Tongue'), [':P', ':-P']),
        ('blush', _('Blushing'), [':">']),
        ('weep', _('Weeping'), [":'-(", ":'("]),
        ('confused', _('Confused'), [':-/', ':/']),
        ('angel', _('Angel'), ['O)', 'O-)', 'O:-)', 'O:)']),
        ('shutup', _("Don't tell anyone"), (':-$', ':-$')),
        ('neutral', _('Neutral'), (':-|', ':|')),
        ('angry', _('Angry'), ('x-(', 'x(', 'X-(', 'x-(')),
        ('devil', _('Devil'), ('>:>', '>:)')),
        ('nerd', _('Nerd'), (':-B', ':B')),
        ('kiss', _('Kiss'), (':-*', ':*')),
        ('laugh', _('Laughing'), [':))']),
        ('sleep', _('Sleepy'), ['I-)']),
        ('sick', _('Sick'), [':-&']),
        ('eyebrow', _('Raised eyebrows'), ['/:)']),
        ]

SMILEY_NAMES = {}

for name, hint_, smilies in SMILIES:
    for i in smilies:
        SMILEY_NAMES[i] = name


SMILIES_COLUMNS = 5
SMILIES_SIZE = int(style.STANDARD_ICON_SIZE * 0.75)


def find_key(dic, val):
		return [k for k, v in dic.iteritems() if v == val][0]

def process_text_for_continuous_smileys(text):
    for key in SMILEY_NAMES.keys():
        text=text.replace(key," "+key+" ")
    return text

###Converts svg into png 
def from_svg_at_size(filename=None, width=None, height=None, handle=None,
        keep_ratio=True):
    """Scale and load SVG into pixbuf"""

    if not handle:
        handle = rsvg.Handle(filename)

    dimensions = handle.get_dimension_data()
    icon_width = dimensions[0]
    icon_height = dimensions[1]
    if icon_width != width or icon_height != height:
        ratio_width = float(width) / icon_width
        ratio_height = float(height) / icon_height

        if keep_ratio:
            ratio = min(ratio_width, ratio_height)
            if ratio_width != ratio:
                ratio_width = ratio
                width = int(icon_width * ratio)
            elif ratio_height != ratio:
                ratio_height = ratio
                height = int(icon_height * ratio)
    else:
        ratio_width = 1
        ratio_height = 1

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    context = cairo.Context(surface)
    context.scale(ratio_width, ratio_height)
    handle.render_cairo(context)

    loader = gtk.gdk.pixbuf_loader_new_with_mime_type('image/png')
    surface.write_to_png(loader)
    loader.close()

    return loader.get_pixbuf()
    
### Invoked on first run to create pngs from svgs and store in ICON_SVG_PATH   
def create_pngs():
    if not exists(ICON_SVG_PATH):
        os.makedirs(ICON_SVG_PATH)

    for name, hint_, smilies_ in SMILIES:
        dst_path = join(ICON_SVG_PATH, name + '.png')
        if exists(dst_path):
            continue
        src_path = join(TEMP_SVG_PATH, name + '.svg')
        pixbuf = from_svg_at_size(src_path,
                SMILIES_SIZE, SMILIES_SIZE, None, True)
        pixbuf.save(dst_path, 'png')
	
##returns an Image for a given smily	
def get_smiley(text):
        file_name=os.path.join(ICON_SVG_PATH , SMILEY_NAMES[text] + '.png')
        surface = cairo.ImageSurface.create_from_png(file_name)
        image = hippo.CanvasImage(image=surface,
                border=0,
                border_color=style.COLOR_BUTTON_GREY.get_int(),
                xalign=hippo.ALIGNMENT_CENTER,
                yalign=hippo.ALIGNMENT_CENTER)
        return image
		
class Chat(ViewSourceActivity):
    def __init__(self, handle):
        super(Chat, self).__init__(handle)

        root = self.make_root()
        self.set_canvas(root)
        root.show_all()
        self.entry.grab_focus()

        toolbar_box = ToolbarBox()
        self.set_toolbar_box(toolbar_box)
        toolbar_box.toolbar.insert(ActivityButton(self), -1)
        toolbar_box.toolbar.insert(TitleEntry(self), -1)
        
        ###check for existence of icons directory
        create_pngs()

        share_button = ShareButton(self)
        toolbar_box.toolbar.insert(share_button, -1)
        toolbar_box.toolbar.insert(KeepButton(self), -1)

        separator = gtk.SeparatorToolItem()
        toolbar_box.toolbar.insert(separator, -1)

        self._smiley = RadioMenuButton(icon_name='smilies')
        self._smiley.palette = Palette(_('Insert smiley'))
        toolbar_box.toolbar.insert(self._smiley, -1)

        table = self._create_pallete_smiley_table()
        table.show_all()
        self._smiley.palette.set_content(table)

        separator = gtk.SeparatorToolItem()
        separator.props.draw = False
        separator.set_expand(True)
        toolbar_box.toolbar.insert(separator, -1)

        toolbar_box.toolbar.insert(StopButton(self), -1)
        toolbar_box.show_all()

        pservice = presenceservice.get_instance()
        self.owner = pservice.get_owner()
        self._chat_log = ''
        # Auto vs manual scrolling:
        self._scroll_auto = True
        self._scroll_value = 0.0
        # Track last message, to combine several messages:
        self._last_msg = None
        self._last_msg_sender = None
        # Chat is room or one to one:
        self._chat_is_room = False
        self.text_channel = None

        if self.shared_activity:
            # we are joining the activity
            self.connect('joined', self._joined_cb)
            if self.get_shared():
                # we have already joined
                self._joined_cb()
        elif handle.uri:
            # XMPP non-Sugar incoming chat, not sharable
            share_button.props.visible = False
            self._one_to_one_connection(handle.uri)
        else:
            # we are creating the activity
            if not self.metadata or self.metadata.get('share-scope',
                    SCOPE_PRIVATE) == SCOPE_PRIVATE:
                # if we are in private session
                self._alert(_('Off-line'), _('Share, or invite someone.'))
            self.connect('shared', self._shared_cb)

    def _create_pallete_smiley_table(self):
        row_count = int(math.ceil(len(SMILIES) / float(SMILIES_COLUMNS)))
        table = gtk.Table(rows=row_count, columns=SMILIES_COLUMNS)
        index = 0

        for y in range(row_count):
            for x in range(SMILIES_COLUMNS):
                name, hint, smilies = SMILIES[index]

                image = gtk.image_new_from_file(
                        join(ICON_SVG_PATH, name + '.png'))
                button = gtk.ToolButton(icon_widget=image)
                button.set_tooltip(gtk.Tooltips(), smilies[0] + ' ' + hint)
                button.connect('clicked', self._add_smiley_to_entry, smilies[0])
                table.attach(button, x, x + 1, y, y + 1)
                button.show()

                index = index + 1
                if index >= len(SMILIES):
                    break

        return table

    def _add_smiley_to_entry(self, button, text):
        pos = self.entry.props.cursor_position
        self.entry.props.buffer.insert_text(pos, text, -1)
        self.entry.set_position(pos + len(text))
        self._smiley.palette.popdown(True)

    def _shared_cb(self, activity):
        logger.debug('Chat was shared')
        self._setup()

    def _one_to_one_connection(self, tp_channel):
        """Handle a private invite from a non-Sugar XMPP client."""
        if self.shared_activity or self.text_channel:
            return
        bus_name, connection, channel = cjson.decode(tp_channel)
        logger.debug('GOT XMPP: %s %s %s', bus_name, connection,
                     channel)
        conn = Connection(
            bus_name, connection, ready_handler=lambda conn: \
            self._one_to_one_connection_ready_cb(bus_name, channel, conn))

    def _one_to_one_connection_ready_cb(self, bus_name, channel, conn):
        """Callback for Connection for one to one connection"""
        text_channel = Channel(bus_name, channel)
        self.text_channel = TextChannelWrapper(text_channel, conn)
        self.text_channel.set_received_callback(self._received_cb)
        self.text_channel.handle_pending_messages()
        self.text_channel.set_closed_callback(
            self._one_to_one_connection_closed_cb)
        self._chat_is_room = False
        self._alert(_('On-line'), _('Private Chat'))

        # XXX How do we detect the sender going offline?
        self.entry.set_sensitive(True)
        self.entry.grab_focus()

    def _one_to_one_connection_closed_cb(self):
        """Callback for when the text channel closes."""
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
        self.entry.set_sensitive(True)
        self.entry.grab_focus()

    def _joined_cb(self, activity):
        """Joined a shared activity."""
        if not self.shared_activity:
            return
        logger.debug('Joined a shared chat')
        for buddy in self.shared_activity.get_joined_buddies():
            self._buddy_already_exists(buddy)
        self._setup()

    def _received_cb(self, buddy, text):
        """Show message that was received."""
        if buddy:
            if type(buddy) is dict:
                nick = buddy['nick']
            else:
                nick = buddy.props.nick
        else:
            nick = '???'
        logger.debug('Received message from %s: %s', nick, text)
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

    def can_close(self):
        """Perform cleanup before closing.
        
        Close text channel of a one to one XMPP chat.
        
        """
        if self._chat_is_room is False:
            if self.text_channel is not None:
                self.text_channel.close()
        return True

    def make_root(self):
        conversation = hippo.CanvasBox(
            spacing=0,
            background_color=COLOR_WHITE.get_int())
        self.conversation = conversation

        entry = gtk.Entry()
        entry.modify_bg(gtk.STATE_INSENSITIVE,
                        COLOR_WHITE.get_gdk_color())
        entry.modify_base(gtk.STATE_INSENSITIVE,
                          COLOR_WHITE.get_gdk_color())
        entry.set_sensitive(False)
        entry.connect('activate', self.entry_activate_cb)
        self.entry = entry

        hbox = gtk.HBox()
        hbox.add(entry)

        sw = hippo.CanvasScrollbars()
        sw.set_policy(hippo.ORIENTATION_HORIZONTAL, hippo.SCROLLBAR_NEVER)
        sw.set_root(conversation)
        self.scrolled_window = sw
        
        vadj = self.scrolled_window.props.widget.get_vadjustment()
        vadj.connect('changed', self.rescroll)
        vadj.connect('value-changed', self.scroll_value_changed_cb)

        canvas = hippo.Canvas()
        canvas.set_root(sw)

        box = gtk.VBox(homogeneous=False)
        box.pack_start(canvas)
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

    def _link_activated_cb(self, link):
        url = url_check_protocol(link.props.text)
        self._show_via_journal(url)
    
	

    def add_text(self, buddy, text, status_message=False):
        """Display text on screen, with name and colors.

        buddy -- buddy object or dict {nick: string, color: string}
                 (The dict is for loading the chat log from the journal,
                 when we don't have the buddy object any more.)
        text -- string, what the buddy said
        status_message -- boolean
            False: show what buddy said
            True: show what buddy did

        hippo layout:
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
        if buddy:
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
            color_fill_rgba = Color(color_fill_html).get_rgba()
            color_fill_gray = (color_fill_rgba[0] + color_fill_rgba[1] +
                               color_fill_rgba[2])/3
            color_stroke = Color(color_stroke_html).get_int()
            color_fill = Color(color_fill_html).get_int()
            if color_fill_gray < 0.5:
                text_color = COLOR_WHITE.get_int()
            else:
                text_color = COLOR_BLACK.get_int()
        else:
            nick = '???'  # XXX: should be '' but leave for debugging
            color_stroke = COLOR_BLACK.get_int()
            color_fill = COLOR_WHITE.get_int()
            text_color = COLOR_BLACK.get_int()
            color = '#000000,#FFFFFF'
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
            msg_hbox = hippo.CanvasBox(
                orientation=hippo.ORIENTATION_HORIZONTAL)
            msg_vbox.append(msg_hbox)
        else:
            rb = CanvasRoundBox(background_color=color_fill,
                                border_color=color_stroke,
                                padding=4)
            rb.props.border_color = color_stroke  # Bug #3742
            self._last_msg = rb
            self._last_msg_sender = buddy
            if not status_message:
                name = hippo.CanvasText(text=nick+':   ',
                    color=text_color,
                    font_desc=FONT_BOLD.get_pango_desc())
                name_vbox = hippo.CanvasBox(
                    orientation=hippo.ORIENTATION_VERTICAL)
                name_vbox.append(name)
                rb.append(name_vbox)
            msg_vbox = hippo.CanvasBox(
                orientation=hippo.ORIENTATION_VERTICAL)
            rb.append(msg_vbox)
            msg_hbox = hippo.CanvasBox(
                orientation=hippo.ORIENTATION_HORIZONTAL)
            msg_vbox.append(msg_hbox)

        if status_message:
            self._last_msg_sender = None

        match = URL_REGEXP.search(text)
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
                msg_hbox.append(message)
            url = text[match.start():match.end()]
            message = hippo.CanvasLink(
                text=url,
                color=text_color,
                font_desc=FONT_BOLD.get_pango_desc(),
                )
            attrs = pango.AttrList()
            attrs.insert(pango.AttrUnderline(pango.UNDERLINE_SINGLE, 0, 32767))
            message.set_property("attributes", attrs)
            message.connect('activated', self._link_activated_cb)

            palette = URLMenu(url)
            palette.props.invoker = CanvasInvoker(message)

            msg_hbox.append(message)
            text = text[match.end():]
            match = URL_REGEXP.search(text)
        if text:
			text=process_text_for_continuous_smileys(text)
			line=text
			
			words=line.split(' ')
			for word in words:
				if word in SMILEY_NAMES:
					
						image=get_smiley(word)					
						msg_hbox.append(image)
						
				else:
					message = hippo.CanvasText(text=word+" ", #change here for changing the typed text
                size_mode=hippo.CANVAS_SIZE_WRAP_WORD,
                color=text_color,
                font_desc=FONT_NORMAL.get_pango_desc(),
                xalign=hippo.ALIGNMENT_START)
					msg_hbox.append(message)
	
        # Order of boxes for RTL languages:
        if lang_rtl:
            msg_hbox.reverse()
            if new_msg:
                rb.reverse()

        if new_msg:
            box = hippo.CanvasBox(padding=2)
            box.append(rb)
            self.conversation.append(box)
    
    def add_separator(self, timestamp):
        """Add whitespace and timestamp between chat sessions."""
        box = hippo.CanvasBox(padding=2)
        time_with_current_year = (time.localtime(time.time())[0],) +\
                time.strptime(timestamp, "%b %d %H:%M:%S")[1:]
        timestamp_seconds = time.mktime(time_with_current_year)
        if timestamp_seconds > time.time():
            time_with_previous_year = (time.localtime(time.time())[0]-1,) +\
                    time.strptime(timestamp, "%b %d %H:%M:%S")[1:]
            timestamp_seconds = time.mktime(time_with_previous_year)
        message = hippo.CanvasText(
            text=timestamp_to_elapsed_string(timestamp_seconds),
            color=COLOR_BUTTON_GREY.get_int(),
            font_desc=FONT_NORMAL.get_pango_desc(),
            xalign=hippo.ALIGNMENT_CENTER)
        box.append(message)
        self.conversation.append(box)
        self._last_msg_sender = None
        self._add_log_timestamp(timestamp)

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

    def _add_log_timestamp(self, existing_timestamp=None):
        """Add a timestamp entry to the chat log."""
        if existing_timestamp is not None:
            self._chat_log += '%s\t\t\n' % existing_timestamp
        else:
            self._chat_log += '%s\t\t\n' % (
                datetime.strftime(datetime.now(), '%b %d %H:%M:%S'))

    def _get_log(self):
        return self._chat_log

    def write_file(self, file_path):
        """Store chat log in Journal.

        Handling the Journal is provided by Activity - we only need
        to define this method.
        """
        logger.debug('write_file: writing %s' % file_path)
        self._add_log_timestamp()
        f = open(file_path, 'w')
        try:
            f.write(self._get_log())
        finally:
            f.close()
        self.metadata['mime_type'] = 'text/plain'

    def read_file(self, file_path):
        """Load a chat log from the Journal.

        Handling the Journal is provided by Activity - we only need
        to define this method.
        """
        logger.debug('read_file: reading %s' % file_path)
        log = open(file_path).readlines()
        last_line_was_timestamp = False
        for line in log:
            if line.endswith('\t\t\n'):
                if last_line_was_timestamp is False:
                    timestamp = line.strip().split('\t')[0]
                    self.add_separator(timestamp)
                    last_line_was_timestamp = True
            else:
                timestamp, nick, color, status, text = line.strip().split('\t')
                status_message = bool(int(status))
                self.add_text({'nick': nick, 'color': color},
                              text, status_message)
                last_line_was_timestamp = False

    def _show_via_journal(self, url):
        """Ask the journal to display a URL"""
        import os
        import time
        from sugar import profile
        from sugar.activity.activity import show_object_in_journal
        from sugar.datastore import datastore
        logger.debug('Create journal entry for URL: %s', url)
        jobject = datastore.create()
        metadata = {
            'title': "%s: %s" % (_('URL from Chat'), url),
            'title_set_by_user': '1',
            'icon-color': profile.get_color().to_string(),
            'mime_type': 'text/uri-list',
            }
        for k,v in metadata.items():
            jobject.metadata[k] = v
        file_path = os.path.join(self.get_activity_root(), 'instance',
                                 '%i_' % time.time())
        open(file_path, 'w').write(url + '\r\n')
        os.chmod(file_path, 0755)
        jobject.set_file_path(file_path)
        datastore.write(jobject)
        show_object_in_journal(jobject.object_id)
        jobject.destroy()
        os.unlink(file_path)


class TextChannelWrapper(object):
    """Wrap a telepathy Text Channel to make usage simpler."""
    def __init__(self, text_chan, conn):
        """Connect to the text channel"""
        self._activity_cb = None
        self._activity_close_cb = None
        self._text_chan = text_chan
        self._conn = conn
        self._logger = logging.getLogger(
            'chat-activity.TextChannelWrapper')
        self._signal_matches = []
        m = self._text_chan[CHANNEL_INTERFACE].connect_to_signal(
            'Closed', self._closed_cb)
        self._signal_matches.append(m)

    def send(self, text):
        """Send text over the Telepathy text channel."""
        # XXX Implement CHANNEL_TEXT_MESSAGE_TYPE_ACTION
        if self._text_chan is not None:
            self._text_chan[CHANNEL_TYPE_TEXT].Send(
                CHANNEL_TEXT_MESSAGE_TYPE_NORMAL, text)

    def close(self):
        """Close the text channel."""
        self._logger.debug('Closing text channel')
        try:
            self._text_chan[CHANNEL_INTERFACE].Close()
        except:
            self._logger.debug('Channel disappeared!')
            self._closed_cb()

    def _closed_cb(self):
        """Clean up text channel."""
        self._logger.debug('Text channel closed.')
        for match in self._signal_matches:
            match.remove()
        self._signal_matches = []
        self._text_chan = None
        if self._activity_close_cb is not None:
            self._activity_close_cb()

    def set_received_callback(self, callback):
        """Connect the function callback to the signal.

        callback -- callback function taking buddy and text args
        """
        if self._text_chan is None:
            return
        self._activity_cb = callback
        m = self._text_chan[CHANNEL_TYPE_TEXT].connect_to_signal('Received',
            self._received_cb)
        self._signal_matches.append(m)

    def handle_pending_messages(self):
        """Get pending messages and show them as received."""
        for id, timestamp, sender, type, flags, text in \
            self._text_chan[
                CHANNEL_TYPE_TEXT].ListPendingMessages(False):
            self._received_cb(id, timestamp, sender, type, flags, text)

    def _received_cb(self, id, timestamp, sender, type, flags, text):
        """Handle received text from the text channel.

        Converts sender to a Buddy.
        Calls self._activity_cb which is a callback to the activity.
        """
        if self._activity_cb:
            try:
                self._text_chan[CHANNEL_INTERFACE_GROUP]
            except:
                # One to one XMPP chat
                nick = self._conn[
                    CONN_INTERFACE_ALIASING].RequestAliases([sender])[0]
                buddy = {'nick': nick, 'color': '#000000,#808080'}
            else:
                # Normal sugar MUC chat
                # XXX: cache these
                buddy = self._get_buddy(sender)
            self._activity_cb(buddy, text)
            self._text_chan[
                CHANNEL_TYPE_TEXT].AcknowledgePendingMessages([id])
        else:
            self._logger.debug('Throwing received message on the floor'
                ' since there is no callback connected. See '
                'set_received_callback')

    def set_closed_callback(self, callback):
        """Connect a callback for when the text channel is closed.

        callback -- callback function taking no args

        """
        self._activity_close_cb = callback

    def _get_buddy(self, cs_handle):
        """Get a Buddy from a (possibly channel-specific) handle."""
        # XXX This will be made redundant once Presence Service 
        # provides buddy resolution
        # Get the Presence Service
        pservice = presenceservice.get_instance()
        # Get the Telepathy Connection
        tp_name, tp_path = pservice.get_preferred_connection()
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

        return pservice.get_buddy_by_telepathy_handle(
            tp_name, tp_path, handle)

class URLMenu(Palette):
    def __init__(self, url):
        Palette.__init__(self, url)

        self.url = url_check_protocol(url)

        menu_item = MenuItem(_('Copy to Clipboard'), 'edit-copy')
        menu_item.connect('activate', self._copy_to_clipboard_cb)
        self.menu.append(menu_item)
        menu_item.show()

    def _copy_to_clipboard_cb(self, menuitem):
        logger.debug('Copy %s to clipboard', self.url)
        clipboard = gtk.clipboard_get()
        targets = [("text/uri-list", 0, 0),
                   ("UTF8_STRING", 0, 1)]

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


def url_check_protocol(url):
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

############# ACTIVITY META-INFORMATION ###############
# this is used by Pippy to generate the Chat bundle.

CHAT_ICON=\
"""<?xml version="1.0" ?><!DOCTYPE svg  PUBLIC '-//W3C//DTD SVG 1.1//EN'  'http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd' [
	<!ENTITY stroke_color "#010101">
	<!ENTITY fill_color "#FFFFFF">
]><svg enable-background="new 0 0 55 55" height="55px" version="1.1" viewBox="0 0 55 55" width="55px" x="0px" xml:space="preserve" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" y="0px"><g display="block" id="activity-chat">
	<path d="M9.263,48.396c0.682,1.152,6.027,0.059,8.246-1.463   c2.102-1.432,3.207-2.596,4.336-2.596c1.133,0,12.54,0.92,20.935-5.715c7.225-5.707,9.773-13.788,4.52-21.437   c-5.252-7.644-13.832-9.08-20.878-8.56C16.806,9.342,4.224,16.91,4.677,28.313c0.264,6.711,3.357,9.143,4.922,10.703   c1.562,1.566,4.545,1.566,2.992,5.588C11.981,46.183,8.753,47.522,9.263,48.396z" display="inline" fill="&fill_color;" stroke="&stroke_color;" stroke-width="3.5"/>
</g></svg><!-- " -->
"""

CHAT_NEWS="""
60

* Version bump to allow for stable releases after v48
* #8772: Fix journal entry creation in Chat for uri-list (kevix)
* #8471: Allow resuming Chat log in Write (morgs)
* #8411: Add license to activity.info (morgs)
* Remove parameter from bundlebuilder.start (morgs)
* Add update_url for software updater (morgs)

45

* Updated translations: sl, nb, el, mr, rw, ur, ne
* Fixed MANIFEST to include all translations (morgs)

44

* #7633: Close the text channel when stopping a 1-1 chat (morgs)
* #7717: Log incoming messages (morgs)
* #7692: Don't show pending messages when joining a chat (morgs)
* Updated translations: nl, te, es, mn

43

* Updated translations: zh_TW, ja

42

* #6036: Show timestamp as elapsed time instead of date (morgs)
* Updated translations: fr, mvo, pis, af, sd, pap, tpi, ar, de

41

* Updated translations: mr, de, ht, km, es, it
* #6036: Add separator after old chat history (morgs)
* #6298: Implement 1-1 private chat with non Sugar Jabber clients (morgs)

40

#5767: Use black text on light fill colors (matthias)

39

* ACK received messages (cassidy)
* Handle pending messages when setting the message handler (cassidy)

38

* Updated translations: zh_TW, de, it

37

* UI Change: Merge multiple sequential messages from same author (morgs)
* Updated translation: ar (pootle)
* #6561: Fix RTL message alignment (Arabic) (khaled)

36

* #5053: Reduce white space around boxes (morgs)
* #6621: set entry sensitive not editable (morgs)
* Add license to activity.py (morgs)
* #6743: border around gtk.entry (morgs)
* Reduce telepathy code based on improved PS channel creation API (morgs)
* Open URLs via show_object_in_journal (morgs)
* Update pippy metadata based on Pippy (morgs)
* Updated translations (pootle)

35

* #6066: Make web links copied to clipboard, pasteable in Write, Browse,
  Terminal (morgs)
* Added AUTHORS, COPYING (morgs)
* Updated translations (pootle)

34

* Updated translations: ur, bn (pootle)
* #2351: Scrolling fixed (marcopg)

33

32

* #5542: Repackaged as a Pippy application. (cscott)

31

* Updated translations: fa, is (pootle)
* #5080: Copy to clipboard with targets (morgs)

30

* Updated translations: es, fr, ne, pt, ro, ru, ur (pootle)
* #5160: Chat should not autoscroll while you scroll up (morgs)

29

* #5080: add a "copy to clipboard" palette for URL's (cassidy)
* Updated translations: fr, es, el, de, ar, zh_TW, it, nl, pt_BR (pootle)

28

* use NotifyAlert from sugar.graphics.alert instead of local
  copy (thanks erikos!) (morgs)

27

* Use sugar.graphics.alert to show status info (morgs)
* #4320: better URL handling and display (morgs)
* #4331: Don't crash/ignore non-Sugar buddies (morgs)

26

* #4320 Better URL support (morgs)

25

* #3417 Resuming shows chat history (morgs)
* self.set_title() considered harmful (morgs)
* New UI look per Eben's mockups (morgs)

24

* #3556: Updated spanish translation (morgs)

23

* Updated spanish translation (morgs)

22

* Revert message dialog added by mistake. (marco)

21

* Add spanish translation (xavi)

20

* Update translation strings - genpot (morgs)
* #3248 Make chat not shared by default (morgs)

19

* Added missing fill_color in icon (erikos)

18

* New activity icon, Fix for #2829 (erikos)

16

* Fix icon and roundbox changes in sugar (morgs)
* Add greek translation (simosx)
* Add arabic translation (khaled)

15

* Rename buddy icon (morgs)
* Regen Chat.pot (danw)
* French translation (marcopg)

14

* #2714 sugar.graphics cleanup (morgs)
* #2578 German translation (morgs)

13

* Added gettext for i18n (morgs)

12

* #2347 Set initial focus on text entry (cassidy)

11

* #2356 Basic link support. (marco)

10

* Adapt to sugar API change (marco)

9

* Fix buddy handles for Salut (Link Local) channels (morgs)
* Show status messages in different colour to text messages (morgs)

8

* Use room provided by PS instead of hardcoded global room (morgs)

"""

def pippy_activity_version():
    """Returns the version number of the generated activity bundle."""
    return 60

def pippy_activity_news():
    """Return the NEWS file for this activity."""
    return CHAT_NEWS

def pippy_activity_icon():
    """Return an SVG document specifying the icon for this activity."""
    return CHAT_ICON

def pippy_activity_class():
    """Return the class which should be started to run this activity."""
    return 'pippy_app.Chat'

def pippy_activity_extra_info():
    return "host_version = 1"
if False: # only the official Chat should have this bundle_id.
    def pippy_activity_bundle_id():
        """Return the bundle_id for the generated activity."""
        return 'org.laptop.Chat'

if __name__ == '__main__':
    print "Use 'Keep As Activity' to create a new version of Chat."
