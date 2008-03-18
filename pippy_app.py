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
import dbus
import hippo
import gtk
import pango
import logging
import re
from datetime import datetime
from activity import ViewSourceActivity

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

class Chat(ViewSourceActivity):
    def __init__(self, handle):
        super(Chat, self).__init__(handle)

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
            message.connect('activated', self._link_activated_cb)

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
        file_path = os.path.join(self.get_activity_root(), 'tmp',
                                 '%i_' % time.time())
        open(file_path, 'w').write(url + '\r\n')
        os.chmod(file_path, 0755)
        jobject.file_path = file_path
        datastore.write(jobject)
        show_object_in_journal(jobject.object_id)
        jobject.destroy()
        os.unlink(file_path)


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
    return 35

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