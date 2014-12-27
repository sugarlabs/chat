import threading
import subprocess

from gi.repository import GObject

GObject.threads_init()


class EbookModeDetector(GObject.GObject):

    EBOOK_DEVICE = '/dev/input/event4'

    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, ([bool])), }

    def __init__(self):
        GObject.GObject.__init__(self)
        self._ebook_mode = self._get_initial_value()
        self._start_reading()

    def get_ebook_mode(self):
        return self._ebook_mode

    def _get_initial_value(self):
        try:
            output = subprocess.call(['evtest', '--query', self.EBOOK_DEVICE,
                                      'EV_SW', 'SW_TABLET_MODE'])
            # 10 is ebook_mode, 0 is normal
            return (output == 10)
        except:
            return False

    def _start_reading(self):
        thread = threading.Thread(target=self._read)
        thread.start()

    def _read(self):
        try:
            fd = open(self.EBOOK_DEVICE, 'rb')
        except:
            return

        for x in range(12):
            fd.read(1)
        value = ord(fd.read(1))
        fd.close()
        self._ebook_mode = (value == 1)
        self.emit('changed', self._ebook_mode)
        # restart
        GObject.idle_add(self._start_reading)
