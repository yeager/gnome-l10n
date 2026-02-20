#!/usr/bin/env python3
"""GNOME L10n — Translation statistics viewer for l10n.gnome.org."""

import gettext
import locale
import os
import subprocess
import sys
import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio, GLib

from gnome_l10n import __version__
from gnome_l10n.api import (
    get_releases, fetch_all_stats, save_cache, load_cache, ModuleStats,
    load_settings, save_settings, DEFAULT_SETTINGS, get_cache_dir,
)

# i18n setup
try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass

TEXTDOMAIN = "gnome-l10n"
LOCALE_DIR = None
for d in [
    os.path.join(os.path.dirname(__file__), "..", "..", "po"),
    "/usr/share/locale",
    "/usr/local/share/locale",
]:
    if os.path.isdir(d):
        LOCALE_DIR = d
        break

if LOCALE_DIR:
    locale.bindtextdomain(TEXTDOMAIN, LOCALE_DIR)
    gettext.bindtextdomain(TEXTDOMAIN, LOCALE_DIR)
gettext.textdomain(TEXTDOMAIN)
_ = gettext.gettext

APP_ID = "se.danielnylander.GnomeL10n"

# Common GNOME languages
LANGUAGES = [
    ("sv", "Swedish"), ("da", "Danish"), ("nb", "Norwegian Bokmål"),
    ("fi", "Finnish"), ("de", "German"), ("fr", "French"),
    ("es", "Spanish"), ("pt_BR", "Portuguese (Brazil)"), ("it", "Italian"),
    ("nl", "Dutch"), ("pl", "Polish"), ("ru", "Russian"),
    ("ja", "Japanese"), ("zh_CN", "Chinese (Simplified)"), ("ko", "Korean"),
    ("uk", "Ukrainian"), ("cs", "Czech"), ("hu", "Hungarian"),
    ("ar", "Arabic"), ("he", "Hebrew"), ("tr", "Turkish"),
    ("pt", "Portuguese"), ("el", "Greek"), ("ca", "Catalan"),
    ("ro", "Romanian"), ("gl", "Galician"), ("eu", "Basque"),
    ("sl", "Slovenian"), ("hr", "Croatian"), ("sr", "Serbian"),
]

SORT_OPTIONS = [
    ("pct_asc", _("Completion % (low → high)")),
    ("pct_desc", _("Completion % (high → low)")),
    ("name_asc", _("Module name (A → Z)")),
    ("name_desc", _("Module name (Z → A)")),
    ("untrans_desc", _("Untranslated (most first)")),
    ("fuzzy_desc", _("Fuzzy (most first)")),
    ("total_desc", _("Total strings (most first)")),
    ("state", _("State")),
]

CACHE_TTL_OPTIONS = [
    (1800, _("30 minutes")),
    (3600, _("1 hour")),
    (7200, _("2 hours")),
    (14400, _("4 hours")),
]


def _open_url(url):
    """Open URL in default browser."""
    try:
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _state_css_class(state):
    """Return CSS class for a vertimus state."""
    s = state.lower() if state else ""
    if s == "translated":
        return "success"
    elif s in ("none", ""):
        return "dim-label"
    elif "commit" in s:
        return "success"
    elif "upload" in s:
        return "accent"
    else:
        return "warning"


class StatsRow(Gtk.Box):
    """A row showing module translation stats with a progress bar."""

    def __init__(self, stats: ModuleStats):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.stats = stats
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # Module name + domain + state
        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        name_box.set_size_request(240, -1)

        # Module name as clickable link
        name_btn = Gtk.Button()
        name_btn.add_css_class("flat")
        name_btn.set_halign(Gtk.Align.START)
        name_label = Gtk.Label(label=stats.module)
        name_label.add_css_class("heading")
        name_label.set_ellipsize(3)
        name_label.set_max_width_chars(28)
        name_btn.set_child(name_label)
        name_btn.set_tooltip_text(_("Open on l10n.gnome.org"))
        name_btn.connect("clicked", lambda *_: _open_url(stats.vertimus_url))
        name_box.append(name_btn)

        # Branch/domain + state
        detail_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        detail_label = Gtk.Label(label=f"{stats.branch} / {stats.domain}")
        detail_label.set_halign(Gtk.Align.START)
        detail_label.add_css_class("dim-label")
        detail_label.add_css_class("caption")
        detail_box.append(detail_label)

        if stats.state:
            state_label = Gtk.Label(label=stats.state)
            state_label.add_css_class("caption")
            state_label.add_css_class(_state_css_class(stats.state))
            detail_box.append(state_label)

        name_box.append(detail_box)
        self.append(name_box)

        # Progress bar
        progress = Gtk.ProgressBar()
        progress.set_fraction(stats.pct / 100.0)
        progress.set_hexpand(True)
        progress.set_valign(Gtk.Align.CENTER)
        progress.set_show_text(True)
        progress.set_text(f"{stats.pct:.0f}%")

        if stats.complete:
            progress.add_css_class("success")
        elif stats.pct >= 80:
            pass
        elif stats.pct >= 50:
            progress.add_css_class("warning")

        self.append(progress)

        # Stats numbers
        nums_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        nums_box.set_size_request(180, -1)

        t_label = Gtk.Label(label=f"✓ {stats.translated}")
        t_label.add_css_class("success")
        t_label.add_css_class("caption")
        nums_box.append(t_label)

        if stats.fuzzy > 0:
            f_label = Gtk.Label(label=f"~ {stats.fuzzy}")
            f_label.add_css_class("warning")
            f_label.add_css_class("caption")
            nums_box.append(f_label)

        if stats.untranslated > 0:
            u_label = Gtk.Label(label=f"✗ {stats.untranslated}")
            u_label.add_css_class("error")
            u_label.add_css_class("caption")
            nums_box.append(u_label)

        total_label = Gtk.Label(label=f"({stats.total})")
        total_label.add_css_class("dim-label")
        total_label.add_css_class("caption")
        nums_box.append(total_label)

        self.append(nums_box)

        # Action buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        # Download PO
        if stats.po_url:
            dl_btn = Gtk.Button(icon_name="document-save-symbolic")
            dl_btn.add_css_class("flat")
            dl_btn.set_tooltip_text(_("Download PO file"))
            dl_btn.connect("clicked", lambda *_: _open_url(stats.po_url))
            btn_box.append(dl_btn)

        # Open vertimus page
        web_btn = Gtk.Button(icon_name="web-browser-symbolic")
        web_btn.add_css_class("flat")
        web_btn.set_tooltip_text(_("Open vertimus page"))
        web_btn.connect("clicked", lambda *_: _open_url(stats.vertimus_url))
        btn_box.append(web_btn)

        self.append(btn_box)


class PreferencesWindow(Adw.PreferencesWindow):
    """Settings window."""

    def __init__(self, parent, settings, **kwargs):
        super().__init__(transient_for=parent, **kwargs)
        self.set_title(_("Preferences"))
        self.set_default_size(500, 400)
        self._settings = settings

        page = Adw.PreferencesPage()

        # General group
        general = Adw.PreferencesGroup(title=_("General"))

        # Default language
        lang_row = Adw.ComboRow(title=_("Default Language"))
        lang_names = [f"{code} — {name}" for code, name in LANGUAGES]
        lang_model = Gtk.StringList.new(lang_names)
        lang_row.set_model(lang_model)
        current_lang = settings.get("default_language", "sv")
        for i, (code, _name) in enumerate(LANGUAGES):
            if code == current_lang:
                lang_row.set_selected(i)
                break
        lang_row.connect("notify::selected", self._on_lang_changed)
        general.add(lang_row)

        # Default release
        release_row = Adw.EntryRow(title=_("Default Release"))
        release_row.set_text(settings.get("default_release", "gnome-49"))
        release_row.connect("changed", self._on_release_changed)
        general.add(release_row)

        page.add(general)

        # Cache group
        cache_grp = Adw.PreferencesGroup(title=_("Cache"))

        ttl_row = Adw.ComboRow(title=_("Cache Duration"))
        ttl_names = [label for _, label in CACHE_TTL_OPTIONS]
        ttl_model = Gtk.StringList.new(ttl_names)
        ttl_row.set_model(ttl_model)
        current_ttl = settings.get("cache_ttl", 3600)
        for i, (val, _) in enumerate(CACHE_TTL_OPTIONS):
            if val == current_ttl:
                ttl_row.set_selected(i)
                break
        ttl_row.connect("notify::selected", self._on_ttl_changed)
        cache_grp.add(ttl_row)

        page.add(cache_grp)
        self.add(page)

    def _on_lang_changed(self, row, _pspec):
        idx = row.get_selected()
        if idx < len(LANGUAGES):
            self._settings["default_language"] = LANGUAGES[idx][0]
            save_settings(self._settings)

    def _on_release_changed(self, row):
        self._settings["default_release"] = row.get_text().strip()
        save_settings(self._settings)

    def _on_ttl_changed(self, row, _pspec):
        idx = row.get_selected()
        if idx < len(CACHE_TTL_OPTIONS):
            self._settings["cache_ttl"] = CACHE_TTL_OPTIONS[idx][0]
            save_settings(self._settings)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_default_size(1200, 850)
        self.set_title(_("GNOME L10n"))

        self._stats = []
        self._settings = load_settings()
        self._release = self._settings.get("default_release", "gnome-49")
        self._language = self._settings.get("default_language", "sv")
        self._dark = False
        self._sort_key = "pct_asc"

        # Main layout
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header bar
        header = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(
            title=_("GNOME L10n"),
            subtitle=_("Translation Statistics")
        )
        header.set_title_widget(title_widget)
        self.title_widget = title_widget

        # Refresh button
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text(_("Refresh (F5)"))
        refresh_btn.connect("clicked", self._on_refresh)
        header.pack_start(refresh_btn)

        # Search
        search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic")
        search_btn.set_tooltip_text(_("Search (Ctrl+F)"))
        search_btn.connect("toggled", self._on_search_toggled)
        header.pack_start(search_btn)
        self.search_btn = search_btn

        # Theme toggle
        theme_btn = Gtk.Button(icon_name="weather-clear-night-symbolic")
        theme_btn.set_tooltip_text(_("Toggle Theme"))
        theme_btn.connect("clicked", self._toggle_theme)
        header.pack_end(theme_btn)
        self.theme_btn = theme_btn

        # Menu
        menu = Gio.Menu()
        menu.append(_("Export CSV"), "win.export")
        menu.append(_("Preferences"), "app.preferences")
        menu.append(_("Keyboard Shortcuts"), "app.shortcuts")
        menu.append(_("About GNOME L10n"), "app.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_btn)

        main_box.append(header)

        # Search bar
        self.search_bar = Gtk.SearchBar()
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self.search_entry.set_placeholder_text(_("Filter modules..."))
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_bar.set_child(self.search_entry)
        self.search_bar.connect_entry(self.search_entry)
        main_box.append(self.search_bar)

        # Controls bar: release + language + sort dropdowns
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        controls.set_margin_top(8)
        controls.set_margin_bottom(8)
        controls.set_margin_start(12)
        controls.set_margin_end(12)

        # Release dropdown
        controls.append(Gtk.Label(label=_("Release:")))
        self.release_dropdown = Gtk.DropDown.new_from_strings([])
        self.release_dropdown.set_size_request(180, -1)
        self.release_dropdown.connect("notify::selected", self._on_release_changed)
        controls.append(self.release_dropdown)

        # Language dropdown
        controls.append(Gtk.Label(label=_("Language:")))
        lang_names = [f"{code} — {name}" for code, name in LANGUAGES]
        self.language_dropdown = Gtk.DropDown.new_from_strings(lang_names)
        self.language_dropdown.set_size_request(220, -1)
        # Select default language
        for i, (code, _) in enumerate(LANGUAGES):
            if code == self._language:
                self.language_dropdown.set_selected(i)
                break
        self.language_dropdown.connect("notify::selected", self._on_language_changed)
        controls.append(self.language_dropdown)

        # Sort dropdown
        controls.append(Gtk.Label(label=_("Sort:")))
        sort_names = [label for _, label in SORT_OPTIONS]
        self.sort_dropdown = Gtk.DropDown.new_from_strings(sort_names)
        self.sort_dropdown.set_size_request(220, -1)
        self.sort_dropdown.connect("notify::selected", self._on_sort_changed)
        controls.append(self.sort_dropdown)

        main_box.append(controls)

        # Filter buttons
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        filter_box.set_margin_start(12)
        filter_box.set_margin_end(12)
        filter_box.set_margin_bottom(8)

        self.filter_all = Gtk.ToggleButton(label=_("All"))
        self.filter_all.set_active(True)
        self.filter_all.connect("toggled", self._on_filter_changed, "all")
        filter_box.append(self.filter_all)

        self.filter_incomplete = Gtk.ToggleButton(label=_("Incomplete"))
        self.filter_incomplete.connect("toggled", self._on_filter_changed, "incomplete")
        filter_box.append(self.filter_incomplete)

        self.filter_complete = Gtk.ToggleButton(label=_("Complete"))
        self.filter_complete.connect("toggled", self._on_filter_changed, "complete")
        filter_box.append(self.filter_complete)

        self.filter_fuzzy = Gtk.ToggleButton(label=_("Has Fuzzy"))
        self.filter_fuzzy.connect("toggled", self._on_filter_changed, "fuzzy")
        filter_box.append(self.filter_fuzzy)

        self.filter_translated = Gtk.ToggleButton(label=_("Translated State"))
        self.filter_translated.connect("toggled", self._on_filter_changed, "state_translated")
        filter_box.append(self.filter_translated)

        main_box.append(filter_box)
        main_box.append(Gtk.Separator())

        # Summary bar
        self.summary_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.summary_box.set_margin_top(8)
        self.summary_box.set_margin_bottom(8)
        self.summary_box.set_margin_start(12)
        self.summary_box.set_margin_end(12)

        self.summary_label = Gtk.Label()
        self.summary_label.set_halign(Gtk.Align.START)
        self.summary_label.add_css_class("heading")
        self.summary_box.append(self.summary_label)

        self.summary_progress = Gtk.ProgressBar()
        self.summary_progress.set_hexpand(True)
        self.summary_progress.set_valign(Gtk.Align.CENTER)
        self.summary_progress.set_show_text(True)
        self.summary_box.append(self.summary_progress)

        main_box.append(self.summary_box)
        main_box.append(Gtk.Separator())

        # Loading spinner
        self.spinner = Gtk.Spinner()
        self.spinner.set_margin_top(12)
        self.spinner.set_visible(False)
        main_box.append(self.spinner)

        self.progress_label = Gtk.Label()
        self.progress_label.add_css_class("dim-label")
        self.progress_label.set_visible(False)
        main_box.append(self.progress_label)

        # Module list
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_margin_top(8)
        self.listbox.set_margin_bottom(8)
        self.listbox.set_margin_start(12)
        self.listbox.set_margin_end(12)
        scroll.set_child(self.listbox)
        main_box.append(scroll)

        # Status bar
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_box.set_margin_start(12)
        status_box.set_margin_end(12)
        status_box.set_margin_top(4)
        status_box.set_margin_bottom(4)
        self.status_label = Gtk.Label(label=_("Loading..."))
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_hexpand(True)
        self.status_label.add_css_class("dim-label")
        self.status_label.add_css_class("caption")
        status_box.append(self.status_label)
        main_box.append(Gtk.Separator())
        main_box.append(status_box)

        self._filter_mode = "all"

        # Actions
        export_action = Gio.SimpleAction.new("export", None)
        export_action.connect("activate", self._on_export)
        self.add_action(export_action)

        # Load releases, then stats
        self._load_releases()

    def _sort_stats(self, stats):
        """Sort stats list based on current sort key."""
        key = self._sort_key
        if key == "pct_asc":
            return sorted(stats, key=lambda s: s.pct)
        elif key == "pct_desc":
            return sorted(stats, key=lambda s: s.pct, reverse=True)
        elif key == "name_asc":
            return sorted(stats, key=lambda s: s.module.lower())
        elif key == "name_desc":
            return sorted(stats, key=lambda s: s.module.lower(), reverse=True)
        elif key == "untrans_desc":
            return sorted(stats, key=lambda s: s.untranslated, reverse=True)
        elif key == "fuzzy_desc":
            return sorted(stats, key=lambda s: s.fuzzy, reverse=True)
        elif key == "total_desc":
            return sorted(stats, key=lambda s: s.total, reverse=True)
        elif key == "state":
            return sorted(stats, key=lambda s: (s.state or "zzz").lower())
        return stats

    def _load_releases(self):
        def do_load():
            try:
                releases = get_releases()
                gnome_releases = [r for r in releases if r["name"].startswith("gnome-")]
                gnome_releases.sort(key=lambda r: r["name"], reverse=True)
                GLib.idle_add(self._on_releases_loaded, gnome_releases)
            except Exception as e:
                GLib.idle_add(self.status_label.set_text, f"Error: {e}")

        threading.Thread(target=do_load, daemon=True).start()

    def _on_releases_loaded(self, releases):
        self._releases = releases
        names = [f"{r['name']} ({r['description']})" for r in releases]
        model = Gtk.StringList.new(names)
        self.release_dropdown.set_model(model)

        # Select configured release
        for i, r in enumerate(releases):
            if r["name"] == self._release:
                self.release_dropdown.set_selected(i)
                break

        self._load_stats()

    def _load_stats(self):
        self.spinner.set_visible(True)
        self.spinner.start()
        self.progress_label.set_visible(True)
        self.progress_label.set_text(_("Loading module statistics..."))

        # Try cache first
        cached = load_cache(self._release, self._language)
        if cached:
            self._on_stats_loaded(cached)
            return

        def do_load():
            def progress(current, total):
                GLib.idle_add(self.progress_label.set_text,
                             _("Loading %d / %d modules...") % (current, total))

            try:
                stats = fetch_all_stats(self._release, self._language, progress_cb=progress)
                save_cache(self._release, self._language, stats)
                GLib.idle_add(self._on_stats_loaded, stats)
            except Exception as e:
                GLib.idle_add(self.status_label.set_text, f"Error: {e}")
                GLib.idle_add(self.spinner.stop)

        threading.Thread(target=do_load, daemon=True).start()

    def _on_stats_loaded(self, stats):
        self._stats = stats
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.progress_label.set_visible(False)
        self._update_view()

    def _update_view(self):
        # Clear listbox
        while True:
            row = self.listbox.get_first_child()
            if row is None:
                break
            self.listbox.remove(row)

        query = self.search_entry.get_text().lower().strip() if self.search_btn.get_active() else ""

        filtered = list(self._stats)
        if self._filter_mode == "incomplete":
            filtered = [s for s in filtered if not s.complete]
        elif self._filter_mode == "complete":
            filtered = [s for s in filtered if s.complete]
        elif self._filter_mode == "fuzzy":
            filtered = [s for s in filtered if s.fuzzy > 0]
        elif self._filter_mode == "state_translated":
            filtered = [s for s in filtered if s.state and s.state.lower() == "translated"]

        if query:
            filtered = [s for s in filtered if query in s.module.lower()]

        # Sort
        filtered = self._sort_stats(filtered)

        for s in filtered:
            row = StatsRow(s)
            self.listbox.append(row)

        # Summary
        total_trans = sum(s.translated for s in self._stats)
        total_fuzzy = sum(s.fuzzy for s in self._stats)
        total_untrans = sum(s.untranslated for s in self._stats)
        total_all = total_trans + total_fuzzy + total_untrans
        pct = (total_trans / total_all * 100) if total_all > 0 else 0
        complete = sum(1 for s in self._stats if s.complete)

        self.summary_label.set_text(
            _("%d modules — %d complete — %d fuzzy — %d untranslated") % (
                len(self._stats), complete, total_fuzzy, total_untrans)
        )
        self.summary_progress.set_fraction(pct / 100)
        self.summary_progress.set_text(f"{pct:.1f}% ({total_trans}/{total_all})")

        now = datetime.now().strftime("%H:%M:%S")
        self.status_label.set_text(
            f"[{now}] {self._release} / {self._language} — "
            + _("%d modules shown, %d total") % (len(filtered), len(self._stats))
        )

    def _on_sort_changed(self, dropdown, _pspec):
        idx = dropdown.get_selected()
        if idx < len(SORT_OPTIONS):
            self._sort_key = SORT_OPTIONS[idx][0]
            self._update_view()

    def _on_release_changed(self, dropdown, _pspec):
        idx = dropdown.get_selected()
        if hasattr(self, '_releases') and idx < len(self._releases):
            self._release = self._releases[idx]["name"]
            self._load_stats()

    def _on_language_changed(self, dropdown, _pspec):
        idx = dropdown.get_selected()
        if idx < len(LANGUAGES):
            self._language = LANGUAGES[idx][0]
            self._load_stats()

    def _on_filter_changed(self, btn, mode):
        if btn.get_active():
            self._filter_mode = mode
            for b, m in [
                (self.filter_all, "all"),
                (self.filter_incomplete, "incomplete"),
                (self.filter_complete, "complete"),
                (self.filter_fuzzy, "fuzzy"),
                (self.filter_translated, "state_translated"),
            ]:
                if m != mode:
                    b.set_active(False)
            self._update_view()

    def _on_search_toggled(self, btn):
        self.search_bar.set_search_mode(btn.get_active())
        if btn.get_active():
            self.search_entry.grab_focus()
        else:
            self._update_view()

    def _on_search_changed(self, entry):
        self._update_view()

    def _on_refresh(self, *_args):
        cache_file = get_cache_dir() / "stats_cache.json"
        if cache_file.exists():
            cache_file.unlink()
        self._load_stats()

    def _on_export(self, *_args):
        import csv, io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Module", "Branch", "Domain", "State", "Translated", "Fuzzy",
                         "Untranslated", "Total", "Percent", "Vertimus URL"])
        for s in self._sort_stats(self._stats):
            writer.writerow([s.module, s.branch, s.domain, s.state, s.translated,
                             s.fuzzy, s.untranslated, s.total, f"{s.pct:.1f}",
                             s.vertimus_url])
        writer.writerow([])
        writer.writerow([f"GNOME L10n v{__version__} — Daniel Nylander"])

        dialog = Gtk.FileDialog.new()
        dialog.set_initial_name(f"gnome-l10n-{self._release}-{self._language}.csv")
        dialog.save(self, None, self._on_export_save, output.getvalue())

    def _on_export_save(self, dialog, result, csv_data):
        try:
            gfile = dialog.save_finish(result)
            path = gfile.get_path()
            with open(path, "w") as f:
                f.write(csv_data)
            self.status_label.set_text(_("Exported to %s") % path)
        except Exception:
            pass

    def _toggle_theme(self, btn):
        mgr = Adw.StyleManager.get_default()
        self._dark = not self._dark
        if self._dark:
            mgr.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            btn.set_icon_name("weather-clear-symbolic")
        else:
            mgr.set_color_scheme(Adw.ColorScheme.DEFAULT)
            btn.set_icon_name("weather-clear-night-symbolic")


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        window = self.props.active_window
        if not window:
            window = MainWindow(application=self)
        window.present()

    def do_startup(self):
        Adw.Application.do_startup(self)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", lambda *_: self.props.active_window._on_refresh() if self.props.active_window else None)
        self.add_action(refresh_action)
        self.set_accels_for_action("app.refresh", ["F5"])

        self.set_accels_for_action("win.search", ["<Primary>f"])

        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", self._on_preferences)
        self.add_action(prefs_action)

        shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
        shortcuts_action.connect("activate", self._on_shortcuts)
        self.add_action(shortcuts_action)
        self.set_accels_for_action("app.shortcuts", ["<Primary>slash"])

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

    def _on_preferences(self, *_args):
        settings = load_settings()
        win = PreferencesWindow(self.props.active_window, settings)
        win.present()

    def _on_shortcuts(self, *_args):
        shortcuts = Gtk.ShortcutsWindow(transient_for=self.props.active_window)
        section = Gtk.ShortcutsSection(section_name="shortcuts", max_height=10)
        group = Gtk.ShortcutsGroup(title=_("General"))
        for accel, title in [
            ("<Primary>q", _("Quit")),
            ("F5", _("Refresh")),
            ("<Primary>f", _("Search")),
            ("<Primary>slash", _("Keyboard Shortcuts")),
        ]:
            shortcut = Gtk.ShortcutsShortcut(accelerator=accel, title=title)
            group.append(shortcut)
        section.append(group)
        shortcuts.add_section(section)
        shortcuts.present()

    def _on_about(self, *_args):
        about = Adw.AboutDialog(
            application_name=_("GNOME L10n"),
            application_icon="preferences-desktop-locale-symbolic",
            developer_name="Daniel Nylander",
            version=__version__,
            developers=["Daniel Nylander"],
            copyright="© 2026 Daniel Nylander",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/yeager/gnome-l10n",
            issue_url="https://github.com/yeager/gnome-l10n/issues",
            comments=_("Translation statistics viewer for GNOME.\nData from l10n.gnome.org."),
            translator_credits=_("translator-credits"),
        )
        about.present(self.props.active_window)


def main():
    app = Application()
    return app.run(sys.argv)


if __name__ == "__main__":
    main()
