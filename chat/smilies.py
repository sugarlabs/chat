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
from gettext import gettext as _
from gi.repository import Gtk, GdkPixbuf, Rsvg
from sugar3.graphics import style
from sugar3.activity.activity import get_bundle_path

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
_catalog = {}

def parse(text):
    """Parse text and find smiles.
    :param text:
    string to parse for smilies
    :returns:
    array of string parts and pixbufs
    """
    
    result = [text]
    
    for smiley in sorted(_catalog.keys(), lambda x, y: cmp(len(y), len(x))):
        new_result = []
        for word in result:
            if isinstance(word, GdkPixbuf.Pixbuf):
                new_result.append(word)
            else:
                parts = word.split(smiley)
                for i in parts[:-1]:
                    new_result.append(i)
                    new_result.append(_catalog[smiley])
                new_result.append(parts[-1])
        result = new_result
        
    return result

def init():
    if _catalog:
        return
    
    svg_dir = os.path.join(get_bundle_path(), 'icons', 'smilies')
    
    for index, (name, hint, codes) in enumerate(THEME):
        archivo = os.path.join(svg_dir, '%s.svg' % (name))
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(archivo, SMILIES_SIZE, SMILIES_SIZE)
        for i in codes:
            _catalog[i] = pixbuf
            THEME[index] = (archivo, hint, codes)
            
