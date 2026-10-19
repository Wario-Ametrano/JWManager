#!/usr/bin/env python3
"""JWManager - a small theme manager for JWM, with a live preview.

Each theme is a folder inside ~/.jwm/themes that contains a .jwmrc file:
    ~/.jwm/themes/<theme-name>/.jwmrc
The folder name is the theme name. Pressing "Apply" copies the file to
~/.jwmrc and restarts JWM. The colors and button style of the app itself
follow the theme that is currently applied.
"""
import filecmp
import glob
import json
import os
import re
import shutil
import subprocess
import threading
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser
import xml.etree.ElementTree as ET

APP_NAME = "JWManager"      # window title, header and WM class

HOME = os.path.expanduser("~")
THEMES_DIR = os.path.join(HOME, ".jwm", "themes")
TARGET = os.path.join(HOME, ".jwmrc")
THEME_FILE = ".jwmrc"
DEFAULT_NAME = "default"
SYSTEM_RC = "/etc/jwm/system.jwmrc"
CACHE_FILE = os.path.join(HOME, ".jwm", "jwmanager-cache.json")   # remembers the logo path

# Symbol (Nerd Font) shown on the panel menu button of the preview.
# To change it, put the code of your symbol here, e.g. "\uf17b8" or "\ue795".
# If no Nerd Font is installed the preview falls back to the text "JWM".
MENU_ICON = "\uebc6"

# Colors of the app itself, used until a theme is applied (minimal, black).
DEFAULT_PALETTE = {
    "bg": "#000000", "fg": "#d8d8d8", "muted": "#8a8a8a", "edge": "#3a3a3a",
    "sel_bg": "#e0e0e0", "sel_fg": "#000000",
    "btn_bg": "#000000", "btn_fg": "#d8d8d8",
    "act_bg": "#e0e0e0", "act_fg": "#000000", "motif": False,
}

# Application icon (PNG, base64): 64 px for the window, 24 px for the header.
ICON_64 = (
    "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"
    "j0A6FV3w4EkAAAAASUVORK5CYII="
)
ICON_24 = (
    "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAEO0lEQVR42p2WTWxUVRTHf+e++958"
    "2DLDTFsJrRpBKhGi7aLWsmFfTZomJviVJrI2QRYGwsKmCYuuSIwJYWciCz9jBVdsXWHTRmo0TE0V"
    "bByFaen0Yyjz8d49LkrHmZbvu3v33nP/53/O//zzBDCAO3HiROry5csjKysrfc65OCA83lJjTGXH"
    "jh1Thw4d+nx8fLwIGAEYHh4+mMvlvllaWtofhiGqypMsEcFaSyaT+b27u/vIhQsXrsixY8fSly5d"
    "ms7n83vK5XJYCyN5/OTrJPCtp/F43O7evXt+cHCw105PT48Ui8U9tVotPHDgJbu362miMETkwSBb"
    "T1UVz1r+yBe4enU2LBaLz05OTh61a2trA2EYaqVclndHjrJ08Aj5G0sY3wO998tOIXJaB1KAMGJX"
    "x04G5ib46MMPJAyTWiqVBqyqWgUxAqVyhXOTSxT/XoLgPgCqEPN485UMVxfKPJsKuFGqkg4M5ZWI"
    "YK2Mb0BRUVVrG2ONGNLpNMvrIL7hnr1WSMYM2WyGbFQmmw6oBVXSMcPOVCtGmuNsgwQQVyP127fs"
    "+OsfbMznfmJyqnwxuUFwRjZIuVqNZzp38c4LNVxD/2ydthjEhWR/Oc9iLkc8Hr+/XBt0poARoVyp"
    "sKu4D/P8MGDq53abElrb2Pty34MBtpRMjHD79jrOM6g268tuHZSoVqVw499HAtiUsohQLpdpb29n"
    "q7q3MbDW0tHR8VAAEWF+fp719XU8z6NSqdDW1rbtnt26EUURhUKBWCz2UAARIZFIoKo45zDGPBhA"
    "RAjDkFQqVQ98lBJdv36dUqnEnTt3tjmAbSyPqjIyMsLCwgK+7z+a+9yNq9VqtLe3c/PmzabELIBz"
    "jmQyydmzZ0mlUqjq/xbQ5DzalPnmQ41Zr6yskEwmcc41M9hUgqriZOMpAYyCqNvUI04F56KNyTcG"
    "EWkCqlQqTYB28+Lq6iqnTp3ixf37WSssEPMsDih7QuTFNwYxquFLRCKRqCcURRGe59V7Nzc3x+nT"
    "p0mlUtub/FQiwfmvvuSNH2fpCwOuBRGf7knz68DHuJZO/NwPvJe8wvgn54gHPmNjY8zMzNDf38/y"
    "8jKFQoHe3t5mBiISbhbXGEMykYCWJGEUoH5EMpGg1ToiGxKLGfwgRrVSQdRhrSUej+N5HtZaEokE"
    "nufV+y8ioW1pafkpCIK3AC0sLjI0+DrLrw0w5VkU5W0AuQZcg44WhH6+n/gOgK6uLrq6ugDIZDL0"
    "9PSQy+Vwzqnv+5JMJifl5MmTOycmJn7O5/PPqWoYBIGISF1B0qCe+tc91LO5X61WVURsZ2dn/vDh"
    "wz0CMDQ01DM7O/v1rVu39lWrVRp9Wu9aed3YUBoNR1WbgIIgIJvN/tnd3X3k4sWLUzI6OmrGxsbc"
    "8ePHM9PT0++vrq6+6pyLPelvS2tr61RfX99nZ86cWRwdHTX/AcBS8trdnZWVAAAAAElFTkSuQmCC"
)


# ---------------------------------------------------------------- parsing
_ENTITY_BAD = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
_ATTR_GAP = re.compile(r'(=\s*"[^"]*")(?=[A-Za-z_])')
_TAG = re.compile(r"<[A-Za-z/][^<>]*>")


def read_xml(path):
    """Read a .jwmrc tolerantly.

    JWM accepts files that a strict XML parser rejects, for example
    unescaped '&' in text or attributes without a space (x="0"y="-1").
    We fix those before parsing the file.
    """
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)       # comments
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)           # xml declaration
    text = _TAG.sub(lambda m: _ATTR_GAP.sub(r"\1 ", m.group(0)), text)
    text = _ENTITY_BAD.sub("&amp;", text)
    return ET.fromstring(text)


def load_roots(path, depth=0, seen=None):
    """Load the file and, recursively, the files it pulls in with <Include>."""
    seen = seen if seen is not None else set()
    path = os.path.abspath(os.path.expanduser(path))
    if path in seen or depth > 3 or not os.path.isfile(path):
        return []
    seen.add(path)
    root = read_xml(path)
    roots = [root]
    for inc in root.iter("Include"):
        target = (inc.text or "").strip()
        if not target or target.startswith("exec:"):
            continue
        target = os.path.expanduser(target)
        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(path), target)
        try:
            roots += load_roots(target, depth + 1, seen)
        except Exception:
            pass  # an included menu may not be valid XML: ignore it
    return roots


def split_grad(spec):
    """'#aaa:#bbb' -> ['#aaa', '#bbb'] (gradient). 'rgb:..' is not a gradient."""
    spec = spec.strip()
    if spec.lower().startswith("rgb:"):
        return [spec]
    return [x.strip() for x in spec.split(":") if x.strip()][:2]


# key -> possible XML paths (the first one found wins)
COLOR_PATHS = {
    "desktop": [".//Desktops/Background"],
    "tray_bg": ["TrayStyle/Background"],
    "tray_fg": ["TrayStyle/Foreground", "TrayStyle/Text"],
    "tray_outline": ["TrayStyle/Outline"],
    "tray_act_bg": ["TrayStyle/Active/Background"],
    "tray_act_fg": ["TrayStyle/Active/Foreground", "TrayStyle/Active/Text"],
    "act_title": ["WindowStyle/Active/Title", "WindowStyle/Active/Background"],
    "act_text": ["WindowStyle/Active/Text", "WindowStyle/Active/Foreground"],
    "act_outline": ["WindowStyle/Active/Outline", "WindowStyle/Outline"],
    "inact_title": ["WindowStyle/Inactive/Title", "WindowStyle/Inactive/Background",
                    "WindowStyle/Background", "WindowStyle/Title"],
    "inact_text": ["WindowStyle/Inactive/Text", "WindowStyle/Inactive/Foreground",
                   "WindowStyle/Foreground", "WindowStyle/Text"],
    "inact_outline": ["WindowStyle/Inactive/Outline", "WindowStyle/Outline"],
    "menu_bg": ["MenuStyle/Background"],
    "menu_fg": ["MenuStyle/Foreground", "MenuStyle/Text"],
    "menu_outline": ["MenuStyle/Outline"],
    "menu_sel_bg": ["MenuStyle/Active/Background"],
    "menu_sel_fg": ["MenuStyle/Active/Foreground", "MenuStyle/Active/Text"],
    "task_bg": ["TaskListStyle/Background"],
    "task_fg": ["TaskListStyle/Foreground", "TaskListStyle/Text"],
    "task_min_bg": ["TaskListStyle/Minimized/Background"],
    "task_min_fg": ["TaskListStyle/Minimized/Foreground"],
    "task_act_bg": ["TaskListStyle/Active/Background"],
    "task_act_fg": ["TaskListStyle/Active/Foreground", "TaskListStyle/Active/Text"],
    "clock_bg": ["ClockStyle/Background"],
    "clock_fg": ["ClockStyle/Foreground", "ClockStyle/Text"],
    "pager_bg": ["PagerStyle/Background"],
    "pager_fg": ["PagerStyle/Foreground"],
    "pager_outline": ["PagerStyle/Outline"],
    "pager_text": ["PagerStyle/Text"],
    "pager_act_bg": ["PagerStyle/Active/Background"],
    "pager_act_fg": ["PagerStyle/Active/Foreground"],
}

# colors used when the theme defines nothing
DEFAULT_COLORS = {
    "desktop": "#2b2b2b", "tray_bg": "#333333", "tray_fg": "#ffffff",
    "act_title": "#444444", "act_text": "#ffffff",
    "inact_title": "#222222", "inact_text": "#999999",
    "menu_bg": "#333333", "menu_fg": "#ffffff",
}
# missing color -> inherit from another color of the theme
FALLBACK = {
    "tray_outline": "tray_bg", "tray_act_bg": "tray_fg", "tray_act_fg": "tray_bg",
    "act_outline": "act_title", "inact_outline": "inact_title",
    "menu_outline": "menu_bg", "menu_sel_bg": "menu_fg", "menu_sel_fg": "menu_bg",
    "task_bg": "tray_bg", "task_fg": "tray_fg",
    "task_act_bg": "task_bg", "task_act_fg": "task_fg",
    "task_min_bg": "task_bg", "task_min_fg": "task_fg",
    "clock_bg": "tray_bg", "clock_fg": "tray_fg",
    "pager_bg": "tray_bg", "pager_fg": "tray_fg", "pager_outline": "tray_bg",
    "pager_text": "tray_fg", "pager_act_bg": "pager_fg", "pager_act_fg": "pager_bg",
}


def parse_theme(path):
    """Extract the main colors and measures from a .jwmrc (JWM 2.3 and 2.4 formats)."""
    t = {"tray_pos": "bottom", "tray_h": 28, "title_h": 22, "border": 1,
         "font": "", "tray_font": "", "icon_paths": [], "note": "",
         "win_deco": "flat", "tray_deco": "flat", "menu_deco": "flat",
         "tray_items": TRAY_DEFAULT, "error": None, "found": 0, "colors": {},
         "desktop_defined": False}
    try:
        roots = load_roots(path)
    except Exception as e:
        t["error"] = str(e)
        return t

    def text_of(el):
        return el.text.strip() if el is not None and el.text and el.text.strip() else None

    def pick(key, paths):
        for root in roots:
            for p in paths:
                for el in root.iterfind(p):
                    val = text_of(el)
                    if not val:
                        continue
                    if key == "desktop":
                        kind = (el.get("type") or "solid").lower()
                        if kind not in ("solid", "gradient"):
                            t["note"] = "'%s' background not shown" % kind
                            continue
                    t["colors"][key] = val
                    if key == "desktop":
                        t["desktop_defined"] = True
                    t["found"] += 1
                    return

    for key, paths in COLOR_PATHS.items():
        pick(key, paths)

    def number(paths, lo, hi, default):
        for root in roots:
            for p in paths:
                v = text_of(root.find(p))
                if v:
                    try:
                        return max(lo, min(hi, int(float(v))))
                    except ValueError:
                        pass
        return default

    # decorations="motif" -> raised bevels (retro look); otherwise "flat"
    for key, tag in (("win_deco", "WindowStyle"), ("tray_deco", "TrayStyle"),
                     ("menu_deco", "MenuStyle")):
        for root in roots:
            el = root.find(tag)
            if el is not None:
                deco = (el.get("decorations") or "").strip().lower()
                t[key] = "motif" if deco == "motif" else "flat"
                break

    t["tray_items"] = parse_tray(roots)
    t["title_h"] = number(["WindowStyle/Height"], 16, 36, 22)
    t["border"] = number(["WindowStyle/Width"], 1, 6, 1)

    for root in roots:
        for p in ("WindowStyle/Font", "MenuStyle/Font"):
            v = text_of(root.find(p))
            if v:
                t["font"] = v
                break
        if t["font"]:
            break

    for root in roots:
        for el in root.iter("IconPath"):
            v = text_of(el)
            if v:
                t["icon_paths"].append(v)

    for root in roots:
        v = text_of(root.find("TrayStyle/Font"))
        if v:
            t["tray_font"] = v
            break

    for root in roots:
        tray = root.find("Tray")
        if tray is None:
            continue
        valign = (tray.get("valign") or "").lower()
        y = (tray.get("y") or "").strip()
        if valign == "top" or (not valign and y in ("0", "+0")):
            t["tray_pos"] = "top"
        try:
            t["tray_h"] = max(20, min(40, int(tray.get("height"))))
        except (TypeError, ValueError):
            pass
        break
    return t


_PARSE_CACHE = {}


def parse_theme_cached(path):
    """parse_theme() with a memory cache: a file is parsed again only if it changed."""
    try:
        st = os.stat(path)
    except OSError:
        return parse_theme(path)
    sig = (st.st_mtime_ns, st.st_size)
    hit = _PARSE_CACHE.get(path)
    if hit and hit[0] == sig:
        return hit[1]
    theme = parse_theme(path)
    _PARSE_CACHE[path] = (sig, theme)
    return theme


LOGO_EXT = (".png", ".gif", ".ppm", ".xpm", ".jpg", ".jpeg", ".bmp")


_LOGO_MEMO = {}


def _load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(data):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass  # the cache is only an optimization


def _search_logo(dirs):
    """One pass over the folders. Preference: file type first, then folder order."""
    found = []
    for rank, d in enumerate(dirs):
        for f in glob.glob(os.path.join(d, "jwm*")):
            ext = os.path.splitext(f)[1].lower()
            if (ext in LOGO_EXT and os.path.isfile(f)
                    and not os.path.basename(f).lower().startswith(APP_NAME.lower())):
                found.append((LOGO_EXT.index(ext), rank, f))
    return min(found)[2] if found else None


def find_logo(icon_paths):
    """Look for the JWM logo. Order: ~/.jwm/jwm-logo.*, the theme's IconPath,
    ~/.jwm/icons, pixmaps and system icons. The first jwm*.<ext> file wins.
    Files starting with the app name (our own icon) are skipped.

    The search can be slow (system icon folders hold thousands of files), so the
    result is remembered in memory and in a small cache file: it runs once, not
    on every redraw."""
    key = "|".join(icon_paths)
    if key in _LOGO_MEMO:
        return _LOGO_MEMO[key]
    own = os.path.join(HOME, ".jwm")
    path = _search_logo([own])                  # cheap: a user-placed logo always wins
    if not path:
        cache = _load_cache()
        cached = cache.get("logo", {}).get(key)
        if cached and os.path.isfile(cached):
            path = cached
        else:
            dirs = [os.path.expanduser(x) for x in icon_paths]
            dirs += [os.path.join(own, "icons"), "/usr/share/pixmaps",
                     "/usr/local/share/pixmaps", "/usr/share/jwm",
                     "/usr/share/icons/hicolor/*/apps", "/usr/share/icons/*/*/apps"]
            path = _search_logo(dirs)
            if path:
                cache.setdefault("logo", {})[key] = path
                _save_cache(cache)
    _LOGO_MEMO[key] = path
    return path


TRAY_DEFAULT = [
    {"type": "button", "label": "", "icon": "", "action": "root:1"},
    {"type": "pager", "labeled": True},
    {"type": "tasklist", "maxwidth": 200},
    {"type": "clock", "format": "%H:%M"},
]


def parse_tray(roots):
    """Read the elements inside <Tray> in the order they appear in the file."""
    def num(v, default):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return default

    for root in roots:
        tray = root.find("Tray")
        if tray is None:
            continue
        items = []
        for el in tray:
            if el.tag == "TrayButton":
                items.append({"type": "button", "label": el.get("label") or "",
                              "icon": el.get("icon") or "",
                              "action": (el.text or "").strip()})
            elif el.tag == "Spacer":
                items.append({"type": "spacer", "w": max(0, num(el.get("width"), 2))})
            elif el.tag == "Pager":
                items.append({"type": "pager",
                              "labeled": (el.get("labeled") or "").lower() == "true"})
            elif el.tag == "TaskList":
                items.append({"type": "tasklist", "maxwidth": num(el.get("maxwidth"), 200)})
            elif el.tag == "Swallow":
                items.append({"type": "swallow", "w": num(el.get("width"), 32)})
            elif el.tag == "Dock":
                # JWM's Dock has a variable number of icons; reserve a modest
                # preview area rather than silently omitting it from the layout.
                items.append({"type": "dock", "w": 64})
            elif el.tag == "Clock":
                items.append({"type": "clock", "format": el.get("format") or "%H:%M"})
        if items:
            return items
    return TRAY_DEFAULT


def font_family(spec):
    """'JetBrainsMono NL Nerd Font-10' / 'Fam:pixelsize=14' -> family name."""
    spec = (spec or "").strip()
    if not spec:
        return ""
    fam = spec.split(":")[0]
    m = re.match(r"^(.*?)-\d+(\.\d+)?$", fam)
    return (m.group(1) if m else fam).strip()


# ----------------------------------------------------------------- logic
def theme_path(name):
    return os.path.join(THEMES_DIR, name, THEME_FILE)


def ensure_setup():
    os.makedirs(THEMES_DIR, exist_ok=True)
    default_path = theme_path(DEFAULT_NAME)
    if not os.path.exists(default_path):
        # Save the current configuration as the "default" theme
        for src in (TARGET, SYSTEM_RC):
            if os.path.exists(src):
                os.makedirs(os.path.dirname(default_path), exist_ok=True)
                shutil.copy2(src, default_path)
                break


def list_themes():
    files = []
    for name in sorted(os.listdir(THEMES_DIR)):
        if name.startswith("."):
            continue
        if os.path.isfile(theme_path(name)):
            files.append(name)
    # the default theme always comes first
    if DEFAULT_NAME in files:
        files.remove(DEFAULT_NAME)
        files.insert(0, DEFAULT_NAME)
    return files


def reload_jwm():
    """Restart JWM (blocking: run it in a thread). Returns (ok, error_message)."""
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    last = ""
    for opt in ("-restart", "-reload"):
        try:
            r = subprocess.run(["jwm", opt], env=env, capture_output=True,
                               text=True, timeout=6)
        except FileNotFoundError:
            return False, "'jwm' command not found in PATH"
        except Exception as e:
            last = str(e)
            continue
        if r.returncode == 0:
            return True, ""
        last = (r.stderr or r.stdout or "exit code %d" % r.returncode).strip()
    return False, last


# -------------------------------------------------------------------- GUI
class App(tk.Tk):
    def __init__(self):
        super().__init__(className=APP_NAME)
        self.title(APP_NAME)
        self.iconname(APP_NAME)
        self.geometry("760x460")
        self.minsize(640, 400)
        self.pal = dict(DEFAULT_PALETTE)
        self._frames, self._labels, self._buttons = [], [], []
        self._set_window_icon()

        ensure_setup()

        left = self._frame(self)
        left.pack(side="left", fill="y", padx=(12, 6), pady=12)
        right = self._frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(6, 12), pady=12)

        # header: icon + app name
        head = self._frame(left)
        head.pack(fill="x", pady=(0, 12))
        try:
            self._header_icon = tk.PhotoImage(data=ICON_24, master=self)
            self._label(head, image=self._header_icon).pack(side="left")
        except tk.TclError:
            pass
        self._label(head, text=APP_NAME, font=("Sans", 11, "bold")).pack(side="left", padx=(6, 0))

        # Compact horizontal section navigation. The active section uses the
        # same colors as JWM's selected menu item in the currently applied theme.
        nav = self._frame(left)
        nav.pack(fill="x", pady=(0, 10))
        self.section_buttons = {}
        for text, section in (("Themes", "themes"), ("Background", "background"), ("Menu", "menu")):
            button = self._button(nav, text, lambda value=section: self.show_section(value))
            button.configure(padx=5, pady=3, takefocus=1)
            button.pack(side="left", fill="x", expand=True, padx=(0, 3))
            self.section_buttons[section] = button

        self.themes_panel = self._frame(left)
        self.themes_panel.pack(fill="both", expand=True)
        self._label(self.themes_panel, text="THEMES", font=("Sans", 10, "bold")).pack(fill="x", pady=(0, 6))
        self.listbox = tk.Listbox(self.themes_panel, relief="flat", bd=0, highlightthickness=1,
                                  activestyle="none", width=24, font=("Sans", 10),
                                  exportselection=False)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.on_select())
        self.listbox.bind("<Double-Button-1>", lambda e: self.apply())
        btns = self._frame(self.themes_panel)
        btns.pack(fill="x", pady=(10, 0))
        for text, cmd in (("Apply", self.apply), ("Reset default", self.reset),
                          ("Reload list", self.refresh)):
            self._button(btns, text, cmd).pack(fill="x", pady=2)

        self.background_panel = self._frame(left)
        self._label(self.background_panel, text="BACKGROUND", font=("Sans", 10, "bold")).pack(fill="x", pady=(0, 8))
        self.bg_mode = tk.StringVar(value="solid")
        self.bg_default = tk.BooleanVar(value=False)
        self.bg_color1 = tk.StringVar(value="#2b2b2b")
        self.bg_color2 = tk.StringVar(value="#387cb0")
        self.bg_radios = []
        for text, value in (("Solid color", "solid"), ("Gradient", "gradient")):
            radio = tk.Radiobutton(self.background_panel, text=text, variable=self.bg_mode,
                                   value=value, command=self._background_changed, anchor="w",
                                   bd=0, highlightthickness=0, padx=2, pady=2)
            radio.pack(fill="x")
            self.bg_radios.append(radio)
        self._label(self.background_panel, text="Color 1").pack(fill="x", pady=(8, 2))
        self.bg_swatch1 = self._button(self.background_panel, "#2b2b2b", lambda: self.choose_bg_color(1))
        self.bg_swatch1.pack(fill="x")
        self._label(self.background_panel, text="Color 2 (gradient)").pack(fill="x", pady=(8, 2))
        self.bg_swatch2 = self._button(self.background_panel, "#387cb0", lambda: self.choose_bg_color(2))
        self.bg_swatch2.pack(fill="x")
        self._button(self.background_panel, "Apply to Theme", self.save_background).pack(fill="x", pady=(14, 3))
        self._button(self.background_panel, "Use JWM Default Background", self.reset_background).pack(fill="x", pady=3)

        self.menu_panel = self._frame(left)
        self._label(self.menu_panel, text="MENU", font=("Sans", 10, "bold")).pack(fill="x", pady=(0, 6))
        self.section = "themes"

        self.preview_heading = self._label(right, text="PREVIEW", font=("Sans", 10, "bold"))
        self.preview_heading.pack(fill="x", pady=(0, 6))
        self.canvas = tk.Canvas(right, highlightthickness=1, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.schedule_draw())

        self.status = tk.Label(right, text="", anchor="w", justify="left",
                               wraplength=440, font=("Sans", 9))
        self.status.pack(fill="x", pady=(8, 0))

        self.theme = None
        self.current = None
        self._draw_job = None
        self._busy = False
        self._fam_cache = None
        self._valid_cache = {}
        self._font_memo = {}
        self.restyle()           # colors of the app follow the applied theme
        self.refresh()
        self.listbox.focus_set()
        self.after(400, self._poll)

    # -- small widget factories (so restyle() can recolor everything later)
    def _frame(self, parent):
        f = tk.Frame(parent)
        self._frames.append(f)
        return f

    def _label(self, parent, **kw):
        lab = tk.Label(parent, anchor="w", **kw)
        self._labels.append(lab)
        return lab

    def _button(self, parent, text, cmd):
        b = tk.Button(parent, text=text, command=cmd, padx=8, pady=6, cursor="hand2")
        self._buttons.append(b)
        return b

    def _set_window_icon(self):
        try:
            self._icon64 = tk.PhotoImage(data=ICON_64, master=self)
            self.iconphoto(True, self._icon64)
        except tk.TclError:
            pass

    def schedule_draw(self):
        """Redraw once the window stops resizing (not on every resize event)."""
        if self._draw_job:
            self.after_cancel(self._draw_job)
        self._draw_job = self.after(60, self._draw_now)

    def _draw_now(self):
        self._draw_job = None
        self.draw()

    def report_callback_exception(self, exc, val, tb):
        """Show errors in the status bar instead of losing them."""
        traceback.print_exception(exc, val, tb)
        self.set_status("ERROR: %s: %s" % (exc.__name__, val))

    def _poll(self):
        """Check the selection even if the list event does not arrive."""
        try:
            sel = self.listbox.curselection()
            if sel and self.listbox.get(sel[0]) != self.current:
                self.on_select()
        except Exception as e:
            self.set_status("ERROR: %s" % e)
        self.after(400, self._poll)

    # -- app colors, taken from the theme that is currently applied (~/.jwmrc)
    def _lum(self, color):
        r, g, b = [v / 65535.0 for v in self.winfo_rgb(color)]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def _mix(self, a, b, t):
        ra, ga, ba = [v // 256 for v in self.winfo_rgb(a)]
        rb, gb, bb = [v // 256 for v in self.winfo_rgb(b)]
        return "#%02x%02x%02x" % (int(ra + (rb - ra) * t), int(ga + (gb - ga) * t),
                                  int(ba + (bb - ba) * t))

    def _readable(self, fg, bg):
        """Keep text readable: if fg is too close to bg use white or black."""
        if abs(self._lum(fg) - self._lum(bg)) >= 0.25:
            return fg
        return "#ffffff" if self._lum(bg) < 0.5 else "#000000"

    def _palette_from(self, theme):
        """Build the app palette from a parsed theme.

        - window/list background  <- menu background (MenuStyle)
        - selected-theme bar      <- selected menu item (MenuStyle/Active)
        - buttons                 <- panel colors and look (TrayStyle); with
                                     decorations="motif" they are raised bevels
        """
        d = DEFAULT_PALETTE
        colors, motif = {}, False
        if theme and not theme["error"]:
            colors = theme["colors"]
            motif = theme["tray_deco"] == "motif"

        def pick(key, default):
            parts = split_grad(colors[key]) if key in colors else []
            return parts[0] if parts and self._valid(parts[0]) else default

        bg = pick("menu_bg", pick("tray_bg", d["bg"]))
        fg = self._readable(pick("menu_fg", d["fg"]), bg)
        sel_bg = pick("menu_sel_bg", d["sel_bg"])
        sel_fg = self._readable(pick("menu_sel_fg", d["sel_fg"]), sel_bg)
        btn_bg = pick("tray_bg", bg)
        btn_fg = self._readable(pick("tray_fg", fg), btn_bg)
        act_bg = pick("tray_act_bg", sel_bg)
        act_fg = self._readable(pick("tray_act_fg", sel_fg), act_bg)
        edge = self._shade(bg, 0.25 if self._lum(bg) < 0.5 else -0.25)
        return {"bg": bg, "fg": fg, "muted": self._mix(fg, bg, 0.45), "edge": edge,
                "sel_bg": sel_bg, "sel_fg": sel_fg, "btn_bg": btn_bg, "btn_fg": btn_fg,
                "act_bg": act_bg, "act_fg": act_fg, "motif": motif}

    def _style_button(self, b):
        p = self.pal
        if p["motif"]:      # panel buttons are raised bevels in this theme
            b.configure(relief="raised", bd=2, highlightthickness=0)
        else:
            b.configure(relief="flat", bd=0, highlightthickness=1,
                        highlightbackground=p["edge"], highlightcolor=p["btn_fg"])
        b.configure(bg=p["btn_bg"], fg=p["btn_fg"],
                    activebackground=p["act_bg"], activeforeground=p["act_fg"])

    def restyle(self):
        """Recolor the whole app from the currently applied theme (~/.jwmrc)."""
        theme = parse_theme_cached(TARGET) if os.path.isfile(TARGET) else None
        p = self._palette_from(theme)
        if p == self.pal and self._frames and getattr(self, "_styled", False):
            return                       # same look: nothing to reconfigure
        self.pal = p
        self._styled = True
        self.configure(bg=p["bg"])
        for f in self._frames:
            f.configure(bg=p["bg"])
        for lab in self._labels:
            lab.configure(bg=p["bg"], fg=p["fg"])
        self.status.configure(bg=p["bg"], fg=p["muted"])
        self.listbox.configure(bg=p["bg"], fg=p["fg"], selectbackground=p["sel_bg"],
                               selectforeground=p["sel_fg"], highlightbackground=p["edge"],
                               highlightcolor=p["edge"])
        self.canvas.configure(bg=p["bg"], highlightbackground=p["edge"],
                              highlightcolor=p["edge"])
        for b in self._buttons:
            self._style_button(b)
        self._style_background_radios()
        self._style_section_buttons()

    def _style_background_radios(self):
        """Use JWM's active-menu colors for the selected background option."""
        p = self.pal
        selected = self.bg_mode.get() if hasattr(self, "bg_mode") else "solid"
        for radio in getattr(self, "bg_radios", []):
            active = radio.cget("value") == selected
            bg = p["sel_bg"] if active else p["bg"]
            fg = p["sel_fg"] if active else p["fg"]
            radio.configure(bg=bg, fg=fg, selectcolor=p["sel_bg"],
                            activebackground=p["sel_bg"] if active else p["bg"],
                            activeforeground=p["sel_fg"] if active else p["fg"],
                            disabledforeground=p["muted"], relief="flat", bd=0,
                            highlightthickness=0)

    def _style_section_buttons(self):
        """Make section navigation match the currently applied JWM theme."""
        if not hasattr(self, "section_buttons"):
            return
        p = self.pal
        for section, button in self.section_buttons.items():
            if section == getattr(self, "section", "themes"):
                # JWM selected menu item: Active background/foreground.
                button.configure(bg=p["sel_bg"], fg=p["sel_fg"],
                                 activebackground=p["sel_bg"], activeforeground=p["sel_fg"])
                if p["motif"]:
                    button.configure(relief="sunken", bd=2, highlightthickness=0)
                else:
                    button.configure(relief="sunken", bd=1, highlightthickness=0)
            else:
                self._style_button(button)

    # -- actions
    def refresh(self):
        _PARSE_CACHE.clear()             # "Reload list" re-reads the theme files
        self.listbox.delete(0, "end")
        self.current = None
        for n in list_themes():
            self.listbox.insert("end", n)
        if self.listbox.size():
            self.listbox.selection_set(0)
            self.on_select()
        else:
            self.theme = None
            self.draw()
            self.set_status("No theme found in %s (needs <theme>/.jwmrc)" % THEMES_DIR)

    def selected(self):
        sel = self.listbox.curselection()
        if sel:
            return self.listbox.get(sel[0])
        return self.current

    def on_select(self):
        name = self.selected()
        if not name:
            return
        self.current = name
        self.theme = parse_theme_cached(theme_path(name))
        if self.theme["error"]:
            msg = "Error in file: " + self.theme["error"]
        else:
            msg = "%s  (colors read: %d/%d)" % (name, self.theme["found"], len(COLOR_PATHS))
            msg += "  - style: %s" % ("motif (raised)" if self.theme["win_deco"] == "motif"
                                     else "flat")
            if self.theme["note"]:
                msg += " - " + self.theme["note"]
        self.set_status(msg)
        self.load_background_controls()
        self.draw()

    def set_status(self, msg):
        self.status.config(text=msg)

    def apply_file(self, name):
        src = theme_path(name)
        try:
            if os.path.exists(TARGET):
                shutil.copy2(TARGET, TARGET + ".bak")
            shutil.copyfile(src, TARGET)
            if not filecmp.cmp(src, TARGET, shallow=False):
                raise IOError("the copied file does not match the original")
        except Exception as e:
            self.set_status("Copy error: %s" % e)
            return
        self.restyle()           # the app takes on the colors of the new theme
        self._busy = True
        self.set_status("Applied %s - restarting JWM ..." % name)
        result = {}

        def work():                       # runs in a thread: the window never freezes
            result["r"] = reload_jwm()

        worker = threading.Thread(target=work, daemon=True)
        worker.start()

        def check():
            if worker.is_alive():
                self.after(100, check)
                return
            self._busy = False
            ok, err = result.get("r", (False, "unknown error"))
            if ok:
                msg = "Applied: %s  ->  %s" % (name, TARGET)
            else:
                msg = "Copied to %s but JWM restart failed: %s" % (TARGET, err)
            print(msg, flush=True)
            self.set_status(msg)

        self.after(100, check)

    def apply(self):
        if self._busy:
            return
        name = self.selected()
        if not name:
            self.set_status("Select a theme in the list first")
            return
        self.set_status("Applying %s ..." % name)
        self.update_idletasks()
        self.apply_file(name)

    def reset(self):
        if self._busy:
            return
        if not os.path.exists(theme_path(DEFAULT_NAME)):
            self.set_status("Theme '%s' not found" % DEFAULT_NAME)
            return
        self.apply_file(DEFAULT_NAME)
        items = list(self.listbox.get(0, "end"))
        if DEFAULT_NAME in items:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(items.index(DEFAULT_NAME))
            self.on_select()

    def show_section(self, section):
        self.section = section
        self._style_section_buttons()
        for panel in (self.themes_panel, self.background_panel, self.menu_panel):
            panel.pack_forget()
        panel = {"themes": self.themes_panel, "background": self.background_panel,
                 "menu": self.menu_panel}[section]
        panel.pack(fill="both", expand=True)
        if section == "background":
            self.load_background_controls()
            self._label_preview_mode("WALLPAPER")
        else:
            self._label_preview_mode("PREVIEW")
        self.draw()

    def _label_preview_mode(self, value):
        # The heading is the first label packed in the right-hand column.
        # Store the preview heading explicitly when available.
        if hasattr(self, "preview_heading"):
            self.preview_heading.config(text=value)

    def load_background_controls(self):
        if not self.theme or self.theme.get("error"):
            return
        spec = self.theme.get("colors", {}).get("desktop", "#2b2b2b")
        colors = split_grad(spec)
        defined = self.theme.get("desktop_defined", False)
        c1 = colors[0] if colors and defined else "#000000"
        c2 = colors[1] if len(colors) > 1 else "#387cb0"
        self.bg_color1.set(c1)
        self.bg_color2.set(c2)
        self.bg_mode.set("gradient" if len(colors) > 1 else "solid")
        self.bg_default.set(not self.theme.get("desktop_defined", False))
        self._update_bg_swatches()

    def _update_bg_swatches(self):
        for button, var in ((self.bg_swatch1, self.bg_color1), (self.bg_swatch2, self.bg_color2)):
            color = var.get()
            button.config(text=color, bg=color, activebackground=color)
            try:
                r, g, b = self.winfo_rgb(color)
                fg = "#000000" if (r + g + b) / 3 > 32767 else "#ffffff"
            except tk.TclError:
                fg = "#ffffff"
            button.config(fg=fg, activeforeground=fg)

    def choose_bg_color(self, which):
        var = self.bg_color1 if which == 1 else self.bg_color2
        try:
            initial = var.get() if self._valid(var.get()) else "#2b2b2b"
            result = colorchooser.askcolor(color=initial, parent=self, title="Choose background color")
            if result and result[1]:
                var.set(result[1])
                self._update_bg_swatches()
                self._background_changed()
        except Exception as exc:
            self.set_status("Color selection error: %s" % exc)

    def _background_changed(self):
        self.bg_default.set(False)
        self._style_background_radios()
        if self.section == "background":
            self.draw()

    def draw_background_preview(self, w, h):
        c = self.canvas
        if self.bg_default.get():
            spec = ("#000000", None)  # JWM's unconfigured desktop background preview
        elif self.bg_mode.get() == "gradient":
            spec = (self.bg_color1.get(), self.bg_color2.get())
        else:
            spec = (self.bg_color1.get(), None)
        if not self._valid(spec[0]) or (spec[1] and not self._valid(spec[1])):
            spec = ("#2b2b2b", None)
        self._fill(0, 0, w, h, spec, vertical=True)
        raw = self.theme or {}
        if not raw or raw.get("error"):
            return
        col = raw["colors"]
        memo = {}
        def S(key):
            if key not in memo:
                memo[key] = self._spec(col, key)
            return memo[key]
        C = lambda key: S(key)[0]
        fam = self._ui_font(raw["font"])
        F = lambda size=9, bold=False: (fam, size, "bold") if bold else (fam, size)
        self._draw_tray(w, h, raw, S, C, F, col)

    def _write_background(self, mode, c1, c2=None):
        path = theme_path(self.selected() or self.current or "")
        if not path or not os.path.isfile(path):
            self.set_status("Select a valid theme first")
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
            bg_re = re.compile(r"<Background\b([^>]*)>(.*?)</Background>", re.S)
            default_marker = re.compile(r"<!--\s*JWManager default background: (none|\s*<Background\b.*?</Background>)\s*-->", re.S)
            has_default_marker = bool(default_marker.search(data))
            desktop_blocks = list(re.finditer(r"<Desktops\b([^>]*)>(.*?)</Desktops>", data, re.S))
            target = None
            for block in desktop_blocks:
                body = block.group(2)
                for match in bg_re.finditer(body):
                    absolute_start = block.start(2) + match.start()
                    if data.rfind("<!--", 0, absolute_start) > data.rfind("-->", 0, absolute_start):
                        continue
                    target = (block, match)
                    break
                if target:
                    break

            if mode == "default":
                # Restore the original theme background if we saved one; otherwise
                # comment out the custom entry so JWM uses its own default.
                if has_default_marker:
                    if target:
                        block, match = target
                        old = match.group(0)
                        abs_start = block.start(2) + match.start()
                        abs_end = block.start(2) + match.end()
                        data = data[:abs_start] + "<!-- JWManager custom background: " + old + " -->" + data[abs_end:]
                    marker_match = default_marker.search(data)
                    if marker_match and marker_match.group(1).strip() == "none":
                        data = default_marker.sub("", data, count=1)
                    else:
                        data = default_marker.sub(lambda m: m.group(1), data, count=1)
                elif target:
                    block, match = target
                    old = match.group(0)
                    abs_start = block.start(2) + match.start()
                    abs_end = block.start(2) + match.end()
                    data = data[:abs_start] + "<!-- JWManager custom background: " + old + " -->" + data[abs_end:]
            else:
                value = c1 if mode == "solid" else c1 + ":" + c2
                new = '<Background type="%s">%s</Background>' % (mode, value)
                if target:
                    block, match = target
                    old = match.group(0)
                    abs_start = block.start(2) + match.start()
                    abs_end = block.start(2) + match.end()
                    if has_default_marker:
                        replacement = new
                    else:
                        # Preserve the theme's original background so Reset can restore it.
                        replacement = "<!-- JWManager default background: " + old + " -->" + new
                    data = data[:abs_start] + replacement + data[abs_end:]
                else:
                    # Insert into an existing Desktops section, expanding self-closing tags if needed.
                    self_closing = re.search(r"<Desktops\b([^>]*)/>", data)
                    if self_closing:
                        replacement = "<Desktops%s><!-- JWManager default background: none -->%s</Desktops>" % (self_closing.group(1), new)
                        data = data[:self_closing.start()] + replacement + data[self_closing.end():]
                    else:
                        opening = re.search(r"<Desktops\b[^>]*>", data)
                        if opening:
                            marker = "" if has_default_marker else "<!-- JWManager default background: none -->"
                            data = data[:opening.end()] + marker + new + data[opening.end():]
                        else:
                            data += "\n<Desktops><!-- JWManager default background: none -->" + new + "</Desktops>\n"
            shutil.copy2(path, path + ".bak")
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
            _PARSE_CACHE.pop(path, None)
            self.theme = parse_theme(path)
            self.load_background_controls()
            self.draw()
            return True
        except Exception as exc:
            self.set_status("Background update error: %s" % exc)
            return False

    def save_background(self):
        if not self.current:
            self.set_status("Select a theme first")
            return
        self.bg_default.set(False)
        c1, c2 = self.bg_color1.get().strip(), self.bg_color2.get().strip()
        if not self._valid(c1) or (self.bg_mode.get() == "gradient" and not self._valid(c2)):
            self.set_status("One of the selected colors is invalid")
            return
        if self._write_background(self.bg_mode.get(), c1, c2):
            # Keep the theme file and the live ~/.jwmrc in sync, then restart JWM.
            self.set_status("Applying background from theme '%s' ..." % self.current)
            self.apply_file(self.current)
            self.show_section("background")

    def reset_background(self):
        if not self.current:
            self.set_status("Select a theme first")
            return
        if self._write_background("default", None):
            self.bg_mode.set("solid")
            self.bg_default.set(True)
            self.bg_color1.set("#000000")
            self.bg_color2.set("#387cb0")
            self._update_bg_swatches()
            self.set_status("Applying JWM default background ...")
            self.apply_file(self.current)
            self.draw()

    # -- preview
    def _valid(self, color):
        ok = self._valid_cache.get(color)
        if ok is None:
            try:
                self.winfo_rgb(color)
                ok = True
            except tk.TclError:
                ok = False
            self._valid_cache[color] = ok
        return ok

    def _families(self):
        if self._fam_cache is None:
            try:
                self._fam_cache = list(tkfont.families(self))
            except Exception:
                self._fam_cache = []
        return self._fam_cache

    def _spec(self, colors, key):
        """Return (color1, color2|None) for the key, following inheritance."""
        seen = set()
        raw = None
        k = key
        while k and k not in seen:
            seen.add(k)
            if k in colors:
                raw = colors[k]
                break
            if k in DEFAULT_COLORS:
                raw = DEFAULT_COLORS[k]
                break
            k = FALLBACK.get(k)
        good = [c for c in split_grad(raw or "#808080") if self._valid(c)]
        if not good:
            good = ["#808080"]
        return good[0], (good[1] if len(good) > 1 else None)

    def _fill(self, x1, y1, x2, y2, spec, vertical=False, outline=""):
        """Solid rectangle or gradient between two colors."""
        c = self.canvas
        c1, c2 = spec
        if not c2:
            c.create_rectangle(x1, y1, x2, y2, fill=c1, outline=outline)
            return
        r1, g1, b1 = [v // 256 for v in self.winfo_rgb(c1)]
        r2, g2, b2 = [v // 256 for v in self.winfo_rgb(c2)]
        length = (y2 - y1) if vertical else (x2 - x1)
        steps = int(max(2, min(length, 64)))
        for i in range(steps):
            f = i / (steps - 1)
            col = "#%02x%02x%02x" % (int(r1 + (r2 - r1) * f), int(g1 + (g2 - g1) * f),
                                     int(b1 + (b2 - b1) * f))
            if vertical:
                ya, yb = y1 + length * i / steps, y1 + length * (i + 1) / steps
                c.create_rectangle(x1, ya, x2, yb + 1, fill=col, outline="")
            else:
                xa, xb = x1 + length * i / steps, x1 + length * (i + 1) / steps
                c.create_rectangle(xa, y1, xb + 1, y2, fill=col, outline="")
        if outline:
            c.create_rectangle(x1, y1, x2, y2, fill="", outline=outline)

    @staticmethod
    def _clock_text(fmt):
        return "12:34 PM" if "%p" in fmt else "12:34"

    def _shade(self, color, f):
        """f>0 lightens (towards white), f<0 darkens (towards black)."""
        r, g, b = [v // 256 for v in self.winfo_rgb(color)]
        if f >= 0:
            r, g, b = [int(v + (255 - v) * f) for v in (r, g, b)]
        else:
            r, g, b = [int(v * (1 + f)) for v in (r, g, b)]
        return "#%02x%02x%02x" % (r, g, b)

    def _bevel(self, x1, y1, x2, y2, base, raised=True, width=1):
        """Raised or sunken bevel, Motif / Windows 98 style."""
        c = self.canvas
        light, dark = self._shade(base, 0.35), self._shade(base, -0.5)
        tl, br = (light, dark) if raised else (dark, light)
        for i in range(width):
            a, b, d, e = x1 + i, y1 + i, x2 - i - 1, y2 - i - 1
            c.create_line(a, b, d, b, fill=tl)
            c.create_line(a, b, a, e, fill=tl)
            c.create_line(a, e, d, e, fill=br)
            c.create_line(d, b, d, e, fill=br)

    def _ui_font(self, raw):
        fam = font_family(raw)
        return fam if fam and fam in self._families() else "Sans"

    def _logo_image(self, icon_paths, size):
        """Resized logo image (None if not found or unreadable)."""
        cache = self.__dict__.setdefault("_logo_cache", {})
        path = find_logo(icon_paths)
        key = (path, size)
        if key in cache:
            return cache[key]
        img = None
        if path:
            try:  # with Pillow: all formats, good quality resizing
                from PIL import Image, ImageTk
                im = Image.open(path).convert("RGBA")
                try:
                    resample = Image.Resampling.LANCZOS
                except AttributeError:
                    resample = Image.LANCZOS
                im.thumbnail((size, size), resample)
                img = ImageTk.PhotoImage(im, master=self)
            except Exception:
                try:  # without Pillow: Tk only reads png/gif/ppm
                    raw = tk.PhotoImage(file=path, master=self)
                    f = max(1, -(-max(raw.width(), raw.height()) // size))
                    img = raw.subsample(f) if f > 1 else raw
                except Exception:
                    img = None
        cache[key] = img
        return img

    def _icon_font(self, tray_font):
        """Find an installed Nerd Font (preferring the tray one)."""
        if tray_font in self._font_memo:
            return self._font_memo[tray_font]
        fams = self._families()
        self._font_memo[tray_font] = self._find_icon_font(fams, tray_font)
        return self._font_memo[tray_font]

    @staticmethod
    def _find_icon_font(fams, tray_font):
        norm = lambda x: re.sub(r"[^a-z0-9]", "", x.lower())
        want = norm(font_family(tray_font))
        if want:
            for f in fams:
                if norm(f) == want:
                    return f
        for f in fams:
            if "nerd" in f.lower():
                return f
        return None

    def draw(self):
        c = self.canvas
        c.delete("all")
        raw = self.theme
        if not raw:
            return
        w, h = c.winfo_width(), c.winfo_height()
        if w < 300 or h < 200:
            return
        col = raw["colors"]
        memo = {}

        def S(key):                                 # (color1, color2|None), computed once
            if key not in memo:
                memo[key] = self._spec(col, key)
            return memo[key]

        C = lambda key: S(key)[0]                   # main color only
        fam = self._ui_font(raw["font"])
        F = lambda size=9, bold=False: (fam, size, "bold") if bold else (fam, size)

        tray_h = raw["tray_h"]
        top_tray = raw["tray_pos"] == "top"
        ay1 = tray_h if top_tray else 0            # usable area (without tray)
        ay2 = h if top_tray else h - tray_h
        H = ay2 - ay1

        # desktop background (solid or vertical gradient)
        if self.section == "background":
            self.draw_background_preview(w, h)
            return
        self._fill(0, 0, w, h, S("desktop"), vertical=True)

        bw = raw["border"]
        th = raw["title_h"]

        def window(x, y, ww, hh, active, label):
            pre = "act" if active else "inact"
            motif = raw["win_deco"] == "motif"
            # flat: frame uses the Outline color; motif: frame uses the title color
            frame = C(pre + "_title") if motif else C(pre + "_outline")
            c.create_rectangle(x, y, x + ww, y + hh, fill=frame, outline="")
            self._fill(x + bw, y + bw, x + ww - bw, y + bw + th, S(pre + "_title"))
            c.create_rectangle(x + bw, y + bw + th, x + ww - bw, y + hh - bw,
                               fill="#1e1e1e", outline="")
            if motif:
                base = C(pre + "_title")
                self._bevel(x, y, x + ww, y + hh, base, True, 2 if bw >= 3 else 1)  # outer
                self._bevel(x + bw - 1, y + bw + th, x + ww - bw + 1, y + hh - bw + 1,
                            base, False, 1)                                  # inner area
            txt = C(pre + "_text")
            c.create_text(x + bw + 8, y + bw + th / 2, text=label, anchor="w",
                          fill=txt, font=F(9, active))
            # buttons at the top right: minimize, maximize, close
            cy = y + bw + th / 2
            r = max(4, int(th * 0.22))
            if motif:
                # three square raised buttons, side by side
                base = C(pre + "_title")
                for i in range(3):                       # 0=close 1=maximize 2=minimize
                    bx2 = x + ww - bw - i * th
                    bx1 = bx2 - th
                    c.create_rectangle(bx1, y + bw, bx2, y + bw + th, fill=base, outline="")
                    self._bevel(bx1, y + bw, bx2, y + bw + th, base, True, 1)
                    cx = (bx1 + bx2) / 2
                    if i == 0:
                        c.create_line(cx - r, cy - r, cx + r + 1, cy + r + 1, fill=txt, width=2)
                        c.create_line(cx - r, cy + r, cx + r + 1, cy - r - 1, fill=txt, width=2)
                    elif i == 1:
                        c.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline=txt, width=2)
                    else:
                        c.create_line(cx - r, cy + r - 1, cx + r + 1, cy + r - 1,
                                      fill=txt, width=2)
            else:
                # flat style: only the symbols, no boxes
                cx = x + ww - bw - 14                    # close (X)
                c.create_line(cx - r, cy - r, cx + r + 1, cy + r + 1, fill=txt, width=1)
                c.create_line(cx - r, cy + r, cx + r + 1, cy - r - 1, fill=txt, width=1)
                cx -= 20                                 # maximize (square)
                c.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline=txt)
                cx -= 20                                 # minimize (dash)
                c.create_line(cx - r, cy + r - 1, cx + r + 1, cy + r - 1, fill=txt, width=2)
            c.create_text(x + bw + 10, y + bw + th + 18, text="Window content",
                          anchor="w", fill="#9a9a9a", font=F(9))

        window(w * 0.05, ay1 + H * 0.10, w * 0.46, H * 0.40, False, "Inactive window")
        window(w * 0.20, ay1 + H * 0.34, w * 0.50, H * 0.46, True, "Active window")

        # menu
        mx, my, mw = w * 0.72, ay1 + H * 0.08, min(w * 0.25, 170)
        items = ("Terminal", "Browser", "Exit")
        ih = 24
        mh = ih * len(items) + 4
        if raw["menu_deco"] == "motif":
            self._fill(mx, my, mx + mw, my + mh, S("menu_bg"))
            self._bevel(mx, my, mx + mw, my + mh, C("menu_bg"), True, 1)
        else:
            c.create_rectangle(mx, my, mx + mw, my + mh, fill=C("menu_outline"), outline="")
            self._fill(mx + 1, my + 1, mx + mw - 1, my + mh - 1, S("menu_bg"))
        for i, label in enumerate(items):
            iy = my + 2 + i * ih
            if i == 1:
                self._fill(mx + 2, iy, mx + mw - 2, iy + ih, S("menu_sel_bg"))
                fg = C("menu_sel_fg")
            else:
                fg = C("menu_fg")
            c.create_text(mx + 10, iy + ih / 2, text=label, anchor="w", fill=fg, font=F(9))

        self._draw_tray(w, h, raw, S, C, F, col)

    def _draw_tray(self, w, h, raw, S, C, F, col):
        # Shared tray renderer used by both Themes and Background previews
        c = self.canvas
        tray_h = raw["tray_h"]
        top_tray = raw["tray_pos"] == "top"
        ty = 0 if top_tray else h - tray_h
        tmotif = raw["tray_deco"] == "motif"
        self._fill(0, ty, w, ty + tray_h, S("tray_bg"), vertical=True)
        if tmotif:
            self._bevel(0, ty, w, ty + tray_h, C("tray_bg"), True, 1)
        else:
            c.create_line(0, ty + (tray_h - 1 if top_tray else 0), w,
                          ty + (tray_h - 1 if top_tray else 0), fill=C("tray_outline"))
        mid = ty + tray_h / 2
        y1, y2 = ty + 1, ty + tray_h - 1

        def tbtn(x1, y1_, x2, y2_, spec, pressed=False):
            """Tray element: flat, or raised/sunken when the tray is motif."""
            self._fill(x1, y1_, x2, y2_, spec)
            if tmotif:
                self._bevel(x1, y1_, x2, y2_, spec[0], not pressed, 1)

        logo = self._logo_image(raw["icon_paths"], tray_h - 2)
        icon_fam = self._icon_font(raw["tray_font"])
        is_pua = lambda ch: 0xE000 <= ord(ch) <= 0xF8FF or ord(ch) >= 0xF0000

        def label_of(text):
            lab = text.strip()
            if lab and any(is_pua(ch) for ch in lab) and not icon_fam:
                return "\u2022"                  # Nerd Font symbol not available
            return lab

        ndesk, cell = 3, int(tray_h * 1.6)

        def width_of(it):
            kind = it["type"]
            if kind == "spacer":
                return it["w"]
            if kind == "pager":
                return ndesk * cell
            if kind == "swallow":
                return min(it["w"], 40) + 2
            if kind == "dock":
                return max(24, min(it.get("w", 64), tray_h * 3))
            if kind == "clock":
                return 14 + 7 * len(self._clock_text(it["format"]))
            if kind == "button":
                if it["action"].startswith("root:"):
                    return int(tray_h * 1.6)
                lab = label_of(it["label"])
                return max(tray_h, 12 + 7 * len(lab)) if lab else tray_h
            return 0                              # tasklist: takes the remaining space

        items = raw["tray_items"]
        flex = max(90, w - 4 - sum(width_of(i) for i in items))
        x = 2
        for it in items:
            kind = it["type"]
            wd = flex if kind == "tasklist" else width_of(it)
            if kind == "button":
                tbtn(x, y1, x + wd, y2, S("tray_bg"))
                if it["action"].startswith("root:"):
                    if logo:
                        c.create_image(x + wd / 2, mid, image=logo)
                    elif icon_fam:
                        c.create_text(x + wd / 2, mid, text=MENU_ICON, fill=C("tray_fg"),
                                      font=(icon_fam, 14))
                    else:
                        c.create_text(x + wd / 2, mid, text="JWM", fill=C("tray_fg"),
                                      font=F(9, True))
                else:
                    lab = label_of(it["label"])
                    if lab:
                        pua = any(is_pua(ch) for ch in it["label"])
                        c.create_text(x + wd / 2, mid, text=lab, fill=C("tray_fg"),
                                      font=(icon_fam, 12) if (pua and icon_fam) else F(9))
                    else:  # button with an icon: placeholder
                        c.create_rectangle(x + wd / 2 - 6, mid - 6, x + wd / 2 + 6, mid + 6,
                                           outline=C("tray_fg"))
            elif kind == "pager":
                for i in range(ndesk):
                    x0, act = x + i * cell, i == 0
                    self._fill(x0, y1, x0 + cell, y2, S("pager_act_bg") if act else S("pager_bg"))
                    if act:  # window thumbnails on the active desktop
                        c.create_rectangle(x0 + 11, y1 + 6, x0 + cell - 7, y2 - 4,
                                           fill=C("pager_fg"), outline=C("pager_outline"))
                        c.create_rectangle(x0 + 5, y1 + 4, x0 + 21, y1 + 13,
                                           fill=C("pager_act_fg"), outline=C("pager_text"))
                    elif it.get("labeled"):
                        c.create_text(x0 + cell / 2, mid, text=str(i + 1),
                                      fill=C("pager_text"), font=F(8))
                    if tmotif:   # separator between desktops (no bevel)
                        sep = self._shade(C("tray_bg"), -0.5)
                        c.create_line(x0 + cell - 1, y1, x0 + cell - 1, y2, fill=sep)
                        c.create_line(x0 + cell, y1, x0 + cell, y2,
                                      fill=self._shade(C("tray_bg"), 0.2))
                    else:
                        c.create_rectangle(x0, y1, x0 + cell, y2, outline=C("pager_outline"))
            elif kind == "tasklist":
                kinds = (("Active window", "task_act_", True), ("Window", "task_", False),
                         ("Minimized", "task_min_", True))
                n = max(1, min(len(kinds), int(wd // 90)))
                iw = max(50, min(it["maxwidth"], int(wd // n) - 2))
                for j, (label, pre, pressed) in enumerate(kinds[:n]):
                    ix = x + j * (iw + 2)
                    tbtn(ix, y1, ix + iw, y2, S(pre + "bg"), pressed=pressed)
                    c.create_rectangle(ix + 5, mid - 5, ix + 15, mid + 5, outline=C(pre + "fg"))
                    c.create_text(ix + 21, mid, text=label, anchor="w", fill=C(pre + "fg"),
                                  font=F(8))
            elif kind == "swallow":
                sz = min(it["w"], 40, tray_h - 2)
                sx = x + 1
                c.create_rectangle(sx, mid - sz / 2, sx + sz, mid + sz / 2,
                                   fill="#ffffff", outline="")
                c.create_oval(sx + 3, mid - sz / 2 + 3, sx + sz - 3, mid + sz / 2 - 3,
                              outline="#d8d8d8")
                c.create_line(sx + sz / 2, mid, sx + sz - 6, mid - 2, fill="#2a6f73", width=2)
            elif kind == "dock":
                # JWM populates the Dock at runtime; keep its space empty in the preview.
                pass
            elif kind == "clock":
                if "clock_bg" in col:
                    self._fill(x, y1, x + wd, y2, S("clock_bg"))
                c.create_text(x + wd / 2, mid, text=self._clock_text(it["format"]),
                              fill=C("clock_fg"), font=F(9))
            x += wd

if __name__ == "__main__":
    App().mainloop()
