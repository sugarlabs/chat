
import dbus
import hippo
import gtk
import pango

from sugar import profile
from sugar.activity.activity import Activity
from sugar.graphics import font
from sugar.graphics.canvasicon import CanvasIcon
from sugar.graphics.entry import Entry
from sugar.graphics.roundbox import RoundBox
from sugar.graphics.button import Button
from sugar.graphics.xocolor import XoColor

tp_name = 'org.freedesktop.Telepathy'
tp_path = '/org/freedesktop/Telepathy'
cm_name = tp_name + '.ConnectionManager'

tp_name = 'org.freedesktop.Telepathy'
tp_path = '/org/freedesktop/Telepathy'
tp_cm_iface = tp_name + '.ConnectionManager'
tp_cm_path = tp_path + '/ConnectionManager'
tp_conn_iface = tp_name + '.Connection'
tp_chan_iface = tp_name + '.Channel'
tp_chan_type_text = tp_chan_iface + '.Type.Text'
tp_conn_aliasing = tp_conn_iface + '.Interface.Aliasing'

room = 'chat@conference.olpc.collabora.co.uk'

class Chat(Activity):
    def __init__(self, handle):
        Activity.__init__(self, handle)

        self.set_title('Chat')

        root = self.make_root()
        self._canvas.set_root(root)
        self._canvas.show()
        self._canvas.show_all()

        self.owner_color = profile.get_color()
        self.owner_nickname = profile.get_nick_name()

        self.add_text(self.owner_nickname, self.make_owner_icon(), 'Hello')
        # test long line
        self.add_text(self.owner_nickname, self.make_owner_icon(),
            'one two three four five six seven eight nine ten ' +
            'one two three four five six seven eight nine ten ' +
            'one two three four five six seven eight nine ten ' +
            'one two three four five six seven eight nine ten')

        bus = dbus.Bus()
        cm = bus.get_object(tp_cm_iface + '.gabble', tp_cm_path + '/gabble')
        cm_iface = dbus.Interface(cm, tp_cm_iface)
        name, path = cm_iface.RequestConnection('jabber', {
            'account': 'test@olpc.collabora.co.uk',
            'password': 'test'
            })
        conn = bus.get_object(name, path)
        conn_iface = dbus.Interface(conn, tp_conn_iface)
        conn_iface.connect_to_signal('StatusChanged', self.status_changed_cb)
        conn_iface.Connect()

        self.conn = conn
        self.conn_iface = conn_iface
        self.conn_name = name
        self.text_iface = None

        self.connect('destroy', self.destroy_cb)

    def destroy_cb(self, _):
        print 'destroy'
        self.conn_iface.Disconnect()

    def received_cb(self, id, timestamp, sender, type, flags, text):
        try:
            aliasing_iface = dbus.Interface(self.conn, tp_conn_aliasing)
            # XXX: cache this
            alias = aliasing_iface.RequestAliases([sender])[0]
            print '%s: %s' % (alias, text)
            icon = CanvasIcon(
                icon_name='theme:stock-buddy',
                xo_color=XoColor('#000000,#ffffff'))
            self.add_text(alias, icon, text)
        except Exception, e:
            print e

    def status_changed_cb(self, status, reason):
        if status == 0:
            try:
                print 'connected'
                bus = dbus.Bus()
                chan_handle = self.conn_iface.RequestHandles(2, [room])[0]
                chan_path = self.conn_iface.RequestChannel(tp_chan_type_text,
                    2, chan_handle, True)
                chan = bus.get_object(self.conn_name, chan_path)
                text_iface = dbus.Interface(chan, tp_chan_type_text)
                text_iface.connect_to_signal('Received', self.received_cb)
                self.text_iface = text_iface
            except Exception, e:
                print e
        elif status == 2:
            print 'disconnected'

    def make_root(self):
        text = hippo.CanvasText(
            text='Hello',
            font_desc=pango.FontDescription('Sans 64'),
            color=0xffffffff)

        conversation = hippo.CanvasBox(spacing=4)
        self.conversation = conversation

        entry = Entry(padding=5)
        entry.connect('activated', self.entry_activated_cb)

        hbox = hippo.CanvasBox(orientation=hippo.ORIENTATION_HORIZONTAL)
        hbox.append(entry, hippo.PACK_EXPAND)

        canvas = hippo.Canvas()
        canvas.set_root(conversation)

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        sw.add_with_viewport(canvas)
        self.scrolled_window = sw

        widget = hippo.CanvasWidget(widget=sw)

        box = hippo.CanvasBox()
        box.append(widget, hippo.PACK_EXPAND)
        box.append(hbox)

        return box

    def make_owner_icon(self):
        return CanvasIcon(
            icon_name='theme:stock-buddy',
            xo_color=self.owner_color)

    def add_text(self, name, icon, text):
        text = hippo.CanvasText(
            text=text,
            size_mode=hippo.CANVAS_SIZE_WRAP_WORD,
            xalign=hippo.ALIGNMENT_START)
        name = hippo.CanvasText(text=name)

        vbox = hippo.CanvasBox(padding=5)

        if icon:
            vbox.append(icon)

        vbox.append(name)

        rb = RoundBox(background_color=0xffffffff, padding=10)
        rb.append(text)

        box = hippo.CanvasBox(
            orientation=hippo.ORIENTATION_HORIZONTAL,
            spacing=10)
        box.append(vbox)
        box.append(rb)

        self.conversation.append(box)

        aw, ah = self.conversation.get_allocation()
        print 'allocation = %r' % ((aw, ah),)
        rw, rh = self.conversation.get_height_request(aw)
        print 'request = %r' % ((rw, rh),)

        adj = self.scrolled_window.get_vadjustment()
        print 'value = %r' % adj.value
        print 'upper = %r' % adj.upper
        print 'page_size = %r' % adj.page_size
        #adj.set_value(adj.upper - adj.page_size)
        #adj.set_value(rh)
        adj.set_value(adj.upper - adj.page_size - 804)

    def entry_activated_cb(self, entry):
        text = entry.props.text
        print `text`

        if text:
            self.add_text(self.owner_nickname, self.make_owner_icon(), text)
            entry.props.text = ''

            if self.text_iface:
                self.text_iface.Send(0, text)

if __name__ == '__main__':
    # hack for running outside sugar

    class _Handle:
        activity_id = 'chat'

        @staticmethod
        def get_presence_service():
            return None

    activity = Chat(_Handle)
    activity.show_all()

    try:
        gtk.main()
    except KeyboardInterrupt:
        pass

