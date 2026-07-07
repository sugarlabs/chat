#!/usr/bin/env python3
import sys
import os
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, Gio

# Set up standalone environment
os.environ.setdefault("SUGAR_BUNDLE_ID", "org.laptop.Chat")
os.environ.setdefault("SUGAR_BUNDLE_NAME", "Chat")
os.environ.setdefault("SUGAR_BUNDLE_PATH", os.getcwd())
os.environ.setdefault("SUGAR_ACTIVITY_ROOT", os.path.expanduser("~/.sugar/default/org.laptop.Chat"))

activity_root = os.environ["SUGAR_ACTIVITY_ROOT"]
for subdir in ["tmp", "instance", "data"]:
    os.makedirs(os.path.join(activity_root, subdir), exist_ok=True)

from sugar4.activity.activityhandle import ActivityHandle
from activity import Chat

# prevent garbage collection of the window
_chat_window = None


def main():
    def on_activate(app):
        global _chat_window
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icon_theme.add_search_path(os.path.join(os.getcwd(), "icons"))

        # Load the CSS Provider if exists
        css_provider = Gtk.CssProvider()
        css_path = os.path.join(os.getcwd(), "activity.css")
        if os.path.exists(css_path):
            css_provider.load_from_path(css_path)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        handle = ActivityHandle(
            activity_id="chat-local",
            object_id="chat-local"
        )
        try:
            _chat_window = Chat(handle)
            app.add_window(_chat_window)
            _chat_window.present()
        except Exception as e:
            print("Failed to launch activity: %s" % e, file=sys.stderr)
            import traceback
            traceback.print_exc()
            app.quit()

    app = Gtk.Application(
        application_id="org.laptop.Chat.local",
        flags=Gio.ApplicationFlags.NON_UNIQUE
    )
    app.connect("activate", on_activate)
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
