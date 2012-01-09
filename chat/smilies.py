# Copyright 2010, Mukesh Gupta
# Copyright 2010, Aleksey Lim
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

import os
from os.path import join, exists
from gettext import gettext as _

import gtk
import cairo

from sugar.graphics import style
from sugar.activity.activity import get_activity_root, get_bundle_path

THEME = [
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :-) and :)
        ('smile', _('Smile'), [':-)', ':)']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are ;-) and ;)
        ('wink', _('Winking'), [';-)', ';)']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :-/ and :/
        ('confused', _('Confused'), [':-/', ':/']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :-( and :(
        ('sad', _('Sad'), [':-(', ':(']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :-D and :D
        ('grin', _('Grin'), [':-D', ':D']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :-| and :|
        ('neutral', _('Neutral'), (':-|', ':|')),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :-O, :O, =-O and =O
        ('shock', _('Shock'), [':-O', ':O', '=-O', '=O']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are B-), B), 8-) and 8)
        ('cool', _('Cool'), ['B-)', 'B)', '8-)', '8)']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :-P and :P
        ('tongue', _('Tongue'), [':-P', ':P']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :">
        ('blush', _('Blushing'), [':">']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :'-( and :'(
        ('weep', _('Weeping'), [":'-(", ":'("]),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are O-), O), O:-) and O:)
        ('angel', _('Angel'), ['O-)', 'O)', 'O:-)', 'O:)']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :-$ and :-$
        ('shutup', _("Don't tell anyone"), (':-$', ':-$')),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are x-(, x(, X-( and x-(
        ('angry', _('Angry'), ('x-(', 'x(', 'X-(', 'x-(')),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are >:> and >:)
        ('devil', _('Devil'), ('>:>', '>:)')),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :-B, :B
        ('nerd', _('Nerd'), (':-B', ':B')),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :-*, :*
        ('kiss', _('Kiss'), (':-*', ':*')),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :))
        ('laugh', _('Laughing'), [':))']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are I-)
        ('sleep', _('Sleepy'), ['I-)']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are :-&
        ('sick', _('Sick'), [':-&']),
        # TRANS: A smiley (http://en.wikipedia.org/wiki/Smiley) explanation
        # TRANS: ASCII-art equivalents are /:)
        ('eyebrow', _('Raised eyebrows'), ['/:)']),
        ]

SMILIES_SIZE = int(style.STANDARD_ICON_SIZE * 0.75)

_catalog = None


def get_pixbuf(word):
    """Return a pixbuf associated to a smile, or None if not available"""
    for (name, __, codes) in THEME:
        if word in codes:
            return gtk.gdk.pixbuf_new_from_file(name)
    return None


def init():
    """Initialise smilies data."""
    global _catalog

    if _catalog is not None:
        return
    _catalog = {}

    png_dir = join(get_activity_root(), 'data', 'icons', 'smilies')
    svg_dir = join(get_bundle_path(), 'icons', 'smilies')

    if not exists(png_dir):
        os.makedirs(png_dir)

    for index, (name, hint, codes) in enumerate(THEME):
        png_path = join(png_dir, name + '.png')

        for i in codes:
            _catalog[i] = png_path
        THEME[index] = (png_path, hint, codes)

        if not exists(png_path):
            pixbuf = _from_svg_at_size(
                    join(svg_dir, name + '.svg'),
                    SMILIES_SIZE, SMILIES_SIZE, None, True)
            pixbuf.save(png_path, 'png')


def _from_svg_at_size(filename=None, width=None, height=None, handle=None,
        keep_ratio=True):
    """Scale and load SVG into pixbuf."""
    import rsvg

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
