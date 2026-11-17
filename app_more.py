"""App mixin: dictionary lookups, VNDB status push, read next. Logic lives in lookups.py / vndb_push.py /
readnext.py; this only wires them to the App. Must not `import tracker`: use `self.lib`."""
import lookups
import readnext
import vndb_push


class MoreMixin:
    def init_more(self):
        self.more_listeners: list = []   # light callbacks (no args), e.g. the Stats lookups tile; TclError removes them
        lookups.ensure(self.store)
        readnext.ensure(self.store)
        vndb_push.install(self)

    # ------------------------------------------------------------------ lookups
    def on_popup(self):
        """The OCR watcher saw meikipop's popup start covering the text box."""
        key = lookups.count_popup(self)
        if key:
            self.notify_more()

    def notify_more(self):
        keep = []
        for fn in self.more_listeners:
            try:
                fn()
                keep.append(fn)
            except Exception:  # noqa: BLE001 - window closed
                pass
        self.more_listeners[:] = keep

    # ------------------------------------------------------------------ VNDB push
    def vndb_test_token(self, callback):
        """callback(text, ok) on the UI thread."""
        vndb_push.test_token(self, callback)

    def set_library_status(self, grp, status):
        """Library status change (pushed to VNDB when enabled) + redraw."""
        self.store.set_status(grp, status)
        self.data_changed()

    # ------------------------------------------------------------------ read next
    def refresh_read_next(self, force=False, callback=None):
        return readnext.refresh(self, force=force, callback=callback)

    def start_reading(self, row):
        grp = readnext.start_reading(self, row)
        self.status(f"started reading {row['title']}", 3500)
        self.data_changed()
        return grp
