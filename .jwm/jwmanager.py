#!/usr/bin/env python3
"""JWManager - a small theme manager for JWM, with a live preview.

Each theme is a folder inside ~/.jwm/themes that contains a .jwmrc file:
    ~/.jwm/themes/<theme-name>/.jwmrc
The folder name is the theme name. Pressing "Apply" copies the file to
~/.jwmrc and restarts JWM. The colors and button style of the app itself
follow the theme that is currently applied.

The window icon is the file ~/.jwm/jwmanager.png. If that file does not exist
the window simply has no icon.
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

APP_NAME = "JWManager"      # window title and WM class

HOME = os.path.expanduser("~")
JWM_DIR = os.path.join(HOME, ".jwm")
THEMES_DIR = os.path.join(JWM_DIR, "themes")
TARGET = os.path.join(HOME, ".jwmrc")
THEME_FILE = ".jwmrc"
DEFAULT_NAME = "Default"
SYSTEM_RC = "/etc/jwm/system.jwmrc"
ICON_FILE = os.path.join(JWM_DIR, "jwmanager.png")            # the only icon used
CACHE_FILE = os.path.join(JWM_DIR, "jwmanager-cache.json")    # remembers the logo path

# Symbol (Nerd Font) shown on the panel menu button of the preview.
# To change it, put the code of your symbol here, e.g. "\uf17b8" or "\ue795".
# If no Nerd Font is installed the preview falls back to the text "JWM".
MENU_ICON = "\uebc6"

# Colors of the app itself, used until a theme is applied (minimal, black).
DEFAULT_PALETTE = {
    "bg": "#000000", "fg": "#d8d8d8", "muted": "#8a8a8a", "edge": "#3a3a3a",
    "sel_bg": "#e0e0e0", "sel_fg": "#000000",
    "btn_bg": "#000000", "btn_fg": "#d8d8d8",
    "act_bg": "#e0e0e0", "act_fg": "#000000",
    "tab_bg": "#e0e0e0", "tab_fg": "#000000", "motif": False,
}


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
_SYSTEM_LOGO = {"done": False, "path": None}
SYSTEM_ICON_DIRS = ["/usr/share/pixmaps", "/usr/local/share/pixmaps", "/usr/share/jwm",
                    "/usr/share/icons/hicolor/*/apps", "/usr/share/icons/*/*/apps"]


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
    """One pass over the folders. Preference: file type first, then folder order.
    Files starting with the app name (our own icon) are never used as the logo."""
    found = []
    own = APP_NAME.lower()
    for rank, d in enumerate(dirs):
        for f in glob.glob(os.path.join(d, "jwm*")):
            ext = os.path.splitext(f)[1].lower()
            if (ext in LOGO_EXT and os.path.isfile(f)
                    and not os.path.basename(f).lower().startswith(own)):
                found.append((LOGO_EXT.index(ext), rank, f))
    return min(found)[2] if found else None


def scan_system_logo():
    """Search the system icon folders ONCE. This can take a while on big icon sets,
    so the app runs it in a background thread and remembers the result on disk."""
    if _SYSTEM_LOGO["done"]:
        return
    cache = _load_cache()
    path = cache.get("system_logo")
    if not (path and os.path.isfile(path)):
        path = _search_logo(SYSTEM_ICON_DIRS)
        if path:
            cache["system_logo"] = path
            _save_cache(cache)
    _SYSTEM_LOGO["path"] = path
    _SYSTEM_LOGO["done"] = True


def find_logo(icon_paths):
    """Look for the JWM logo: ~/.jwm, the theme's IconPath, ~/.jwm/icons, then the
    system icons (found by scan_system_logo). Cheap: it never scans the system."""
    key = tuple(icon_paths)
    if key in _LOGO_MEMO:
        return _LOGO_MEMO[key]
    dirs = [JWM_DIR] + [os.path.expanduser(p) for p in icon_paths]
    dirs.append(os.path.join(JWM_DIR, "icons"))
    path = _search_logo(dirs) or _SYSTEM_LOGO["path"]
    if path or _SYSTEM_LOGO["done"]:        # do not remember "not found" while scanning
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


# ------------------------------------------------------------ desktop background in a theme file
_BG_RE = re.compile(r"<Background\b([^>]*)>(.*?)</Background>", re.S)
_DEFAULT_BG_MARK = re.compile(
    r"<!--\s*JWManager default background: (none|\s*<Background\b.*?</Background>)\s*-->", re.S)
_DESKTOPS_RE = re.compile(r"<Desktops\b([^>]*)>(.*?)</Desktops>", re.S)


def _find_active_background(data):
    """(start, end, text) of the first <Background> inside <Desktops> that is not
    inside an XML comment, or None."""
    for block in _DESKTOPS_RE.finditer(data):
        body_start = block.start(2)
        for m in _BG_RE.finditer(block.group(2)):
            start = body_start + m.start()
            if data.rfind("<!--", 0, start) > data.rfind("-->", 0, start):
                continue
            return start, body_start + m.end(), m.group(0)
    return None


def rewrite_background(data, mode, c1=None, c2=None):
    """Return the theme text with the desktop background changed.

    mode "solid" / "gradient": set the color(s). The theme's original background is
    kept inside a comment so that mode "default" can restore it later.
    mode "default": go back to the original background (or none)."""
    found = _find_active_background(data)
    has_marker = bool(_DEFAULT_BG_MARK.search(data))
    if mode == "default":
        if has_marker:
            if found:
                s, e, old = found
                data = data[:s] + "<!-- JWManager custom background: " + old + " -->" + data[e:]
            m = _DEFAULT_BG_MARK.search(data)
            if m and m.group(1).strip() == "none":
                data = _DEFAULT_BG_MARK.sub("", data, count=1)
            else:
                data = _DEFAULT_BG_MARK.sub(lambda mm: mm.group(1), data, count=1)
        elif found:
            s, e, old = found
            data = data[:s] + "<!-- JWManager custom background: " + old + " -->" + data[e:]
        return data

    value = c1 if mode == "solid" else c1 + ":" + c2
    new = '<Background type="%s">%s</Background>' % (mode, value)
    if found:
        s, e, old = found
        repl = new if has_marker else "<!-- JWManager default background: " + old + " -->" + new
        return data[:s] + repl + data[e:]
    closed = re.search(r"<Desktops\b([^>]*)/>", data)       # <Desktops ... />
    if closed:
        repl = "<Desktops%s><!-- JWManager default background: none -->%s</Desktops>" % (
            closed.group(1), new)
        return data[:closed.start()] + repl + data[closed.end():]
    opening = re.search(r"<Desktops\b[^>]*>", data)
    if opening:
        marker = "" if has_marker else "<!-- JWManager default background: none -->"
        return data[:opening.end()] + marker + new + data[opening.end():]
    block = "\n<Desktops><!-- JWManager default background: none -->" + new + "</Desktops>\n"
    end = data.rfind("</JWM>")                 # keep the XML valid: add it inside <JWM>
    return data + block if end < 0 else data[:end] + block + data[end:]


# -------------------------------------------------------------------- GUI
_HEX6 = re.compile(r"^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$")


class App(tk.Tk):
    PANEL_W = 238         # width of the left column (list + buttons)

    def __init__(self):
        super().__init__(className=APP_NAME)
        self.title(APP_NAME)
        self.iconname(APP_NAME)
        self.geometry("762x472")
        self.minsize(660, 420)
        self.pal = dict(DEFAULT_PALETTE)
        self._frames, self._labels, self._buttons = [], [], []
        self._rgb_cache, self._edge_cache = {}, {}
        self._fam_cache, self._font_memo = None, {}
        self._draw_job, self._drawn_key = None, None
        self._status_wrap = 0
        self._theme_rev = 0
        self._busy = False
        self._styled = False
        self.theme = None
        self.current = None
        self.section = "themes"

        self._load_window_icon()
        ensure_setup()
        self._build_ui()
        self.restyle()           # colors of the app follow the applied theme
        self.refresh()
        self.listbox.focus_set()
        self._start_logo_scan()

    # -- window icon: only ~/.jwm/jwmanager.png, nothing built in
    def _load_window_icon(self):
        try:
            if os.path.isfile(ICON_FILE):
                self._icon = tk.PhotoImage(file=ICON_FILE, master=self)
                self.iconphoto(True, self._icon)
        except tk.TclError:
            pass                 # unreadable file: no icon

    # -- small widget factories (so restyle() can recolor everything later)
    def _frame(self, parent, **kw):
        f = tk.Frame(parent, **kw)
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

    # -- layout (see the mockup): tabs + status on top, list/buttons left, preview right
    def _build_ui(self):
        main = self._frame(self)
        main.pack(fill="both", expand=True, padx=14, pady=14)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(1, weight=1)

        nav = self._frame(main)
        nav.grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.section_buttons = {}
        for text, section in (("Themes", "themes"), ("Background", "background"),
                              ("Menu", "menu")):
            b = self._button(nav, text, lambda value=section: self.show_section(value))
            b.configure(padx=9, pady=3, takefocus=1)
            b.pack(side="left", padx=(0, 4))
            self.section_buttons[section] = b

        # fixed-height box: a long status message never moves the rest of the layout
        status_box = self._frame(main, height=34)
        status_box.pack_propagate(False)
        status_box.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=(0, 10))
        self.status = tk.Label(status_box, text="", anchor="w", justify="left",
                               font=("Sans", 9))
        self.status.pack(fill="both", expand=True)
        self.status.bind("<Configure>", self._on_status_resize)

        left = self._frame(main, width=self.PANEL_W)
        left.pack_propagate(False)
        left.grid(row=1, column=0, sticky="ns")
        self._build_themes_panel(left)
        self._build_background_panel(left)
        self.menu_panel = self._frame(left)
        self._label(self.menu_panel, text="Menu management is not available yet.").pack(
            fill="x", pady=(2, 0))
        self.themes_panel.pack(fill="both", expand=True)

        right = self._frame(main)
        right.grid(row=1, column=1, sticky="nsew", padx=(12, 0))
        self.canvas = tk.Canvas(right, highlightthickness=1, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.schedule_draw())

    def _build_themes_panel(self, left):
        self.themes_panel = self._frame(left)
        btns = self._frame(self.themes_panel)
        btns.pack(side="bottom", fill="x", pady=(14, 0))
        for text, cmd in (("Apply", self.apply), ("Reset default", self.reset),
                          ("Reload list", self.refresh)):
            self._button(btns, text, cmd).pack(fill="x", pady=2)
        self.listbox = tk.Listbox(self.themes_panel, relief="flat", bd=0, highlightthickness=1,
                                  activestyle="none", width=10, font=("Sans", 10),
                                  exportselection=False)
        self.listbox.pack(fill="both", expand=True)
        # No polling: every way of changing the selection is bound instead.
        for seq in ("<<ListboxSelect>>", "<ButtonRelease-1>", "<KeyRelease-Up>",
                    "<KeyRelease-Down>", "<KeyRelease-Prior>", "<KeyRelease-Next>",
                    "<KeyRelease-Home>", "<KeyRelease-End>"):
            self.listbox.bind(seq, lambda e: self._select_changed())
        self.listbox.bind("<Double-Button-1>", lambda e: self.apply())

    def _build_background_panel(self, left):
        self.background_panel = self._frame(left)
        panel = self.background_panel
        self.bg_mode = tk.StringVar(value="solid")
        self.bg_default = tk.BooleanVar(value=False)
        self.bg_color1 = tk.StringVar(value="#2b2b2b")
        self.bg_color2 = tk.StringVar(value="#387cb0")
        self.bg_radios = []
        for text, value in (("Solid color", "solid"), ("Gradient", "gradient")):
            radio = tk.Radiobutton(panel, text=text, variable=self.bg_mode, value=value,
                                   command=self._background_changed, anchor="w",
                                   bd=0, highlightthickness=0, padx=2, pady=2)
            radio.pack(fill="x")
            self.bg_radios.append(radio)
        self._label(panel, text="Color 1").pack(fill="x", pady=(8, 2))
        self.bg_swatch1 = self._button(panel, "#2b2b2b", lambda: self.choose_bg_color(1))
        self.bg_swatch1.pack(fill="x")
        self._label(panel, text="Color 2 (gradient)").pack(fill="x", pady=(8, 2))
        self.bg_swatch2 = self._button(panel, "#387cb0", lambda: self.choose_bg_color(2))
        self.bg_swatch2.pack(fill="x")
        self._button(panel, "Apply to Theme", self.save_background).pack(fill="x", pady=(14, 3))
        self._button(panel, "Use JWM Default Background", self.reset_background).pack(
            fill="x", pady=3)

    # -- status line
    def _on_status_resize(self, event):
        wrap = max(100, event.width - 4)
        if abs(wrap - self._status_wrap) > 2:       # the box has a fixed height: no layout loop
            self._status_wrap = wrap
            self.status.configure(wraplength=wrap)

    def set_status(self, msg):
        self.status.config(text=msg)

    # -- logo scan: slow part of the work, kept out of the user interface
    def _start_logo_scan(self):
        worker = threading.Thread(target=scan_system_logo, daemon=True)
        worker.start()

        def check():
            if worker.is_alive():
                self.after(150, check)
            else:
                _LOGO_MEMO.clear()
                self.draw(force=True)        # the logo may be available now
        self.after(150, check)

    # -- drawing is debounced: once the window stops resizing, not on every event
    def schedule_draw(self):
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

    def _select_changed(self):
        sel = self.listbox.curselection()
        if sel and self.listbox.get(sel[0]) != self.current:
            self.on_select()

    # -- colors (fast path for #rrggbb, Tk only for color names; results are cached)
    def _rgb(self, color):
        """(r, g, b) in 0..255, or None if the color is not valid."""
        v = self._rgb_cache.get(color, False)
        if v is False:
            m = _HEX6.match(color) if isinstance(color, str) else None
            if m:
                v = (int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16))
            else:
                try:
                    v = tuple(x // 256 for x in self.winfo_rgb(color))
                except tk.TclError:
                    v = None
            self._rgb_cache[color] = v
        return v

    def _valid(self, color):
        return self._rgb(color) is not None

    def _lum(self, color):
        r, g, b = self._rgb(color)
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0

    def _mix(self, a, b, t):
        ra, ga, ba = self._rgb(a)
        rb, gb, bb = self._rgb(b)
        return "#%02x%02x%02x" % (int(ra + (rb - ra) * t), int(ga + (gb - ga) * t),
                                  int(ba + (bb - ba) * t))

    def _shade(self, color, f):
        """f>0 lightens (towards white), f<0 darkens (towards black)."""
        r, g, b = self._rgb(color)
        if f >= 0:
            r, g, b = [int(v + (255 - v) * f) for v in (r, g, b)]
        else:
            r, g, b = [int(v * (1 + f)) for v in (r, g, b)]
        return "#%02x%02x%02x" % (r, g, b)

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
        - selected section tab    <- the panel's active window button (TaskListStyle/Active)
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
        tab_bg = pick("task_act_bg", act_bg)
        tab_fg = self._readable(pick("task_act_fg", act_fg), tab_bg)
        edge = self._shade(bg, 0.25 if self._lum(bg) < 0.5 else -0.25)
        return {"bg": bg, "fg": fg, "muted": self._mix(fg, bg, 0.45), "edge": edge,
                "sel_bg": sel_bg, "sel_fg": sel_fg, "btn_bg": btn_bg, "btn_fg": btn_fg,
                "act_bg": act_bg, "act_fg": act_fg, "tab_bg": tab_bg, "tab_fg": tab_fg,
                "motif": motif}

    def _style_button(self, b):
        p = self.pal
        if p["motif"]:      # panel buttons are raised bevels in this theme
            b.configure(relief="raised", bd=2, highlightthickness=0)
        else:
            b.configure(relief="flat", bd=0, highlightthickness=1,
                        highlightbackground=p["edge"], highlightcolor=p["btn_fg"])
        b.configure(bg=p["btn_bg"], fg=p["btn_fg"],
                    activebackground=p["act_bg"], activeforeground=p["act_fg"])

    def _style_background_radios(self):
        """Use JWM's active-menu colors for the selected background option."""
        p = self.pal
        selected = self.bg_mode.get()
        for radio in self.bg_radios:
            active = radio.cget("value") == selected
            bg = p["sel_bg"] if active else p["bg"]
            fg = p["sel_fg"] if active else p["fg"]
            radio.configure(bg=bg, fg=fg, selectcolor=p["sel_bg"],
                            activebackground=bg, activeforeground=fg,
                            disabledforeground=p["muted"], relief="flat", bd=0,
                            highlightthickness=0)

    def _style_section_buttons(self):
        """Tabs look like the panel buttons; the selected one is pressed in, like the
        active window button of the JWM panel."""
        p = self.pal
        for section, button in self.section_buttons.items():
            if section == self.section:
                button.configure(bg=p["tab_bg"], fg=p["tab_fg"],
                                 activebackground=p["tab_bg"], activeforeground=p["tab_fg"])
                if p["motif"]:
                    button.configure(relief="sunken", bd=2, highlightthickness=0)
                else:
                    button.configure(relief="flat", bd=0, highlightthickness=1,
                                     highlightbackground=p["tab_fg"],
                                     highlightcolor=p["tab_fg"])
            else:
                self._style_button(button)

    def restyle(self):
        """Recolor the whole app from the currently applied theme (~/.jwmrc)."""
        theme = parse_theme_cached(TARGET) if os.path.isfile(TARGET) else None
        p = self._palette_from(theme)
        if self._styled and p == self.pal:
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
        self._update_bg_swatches()       # the swatches show their own colors

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
            self._set_theme(None)
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
        self._set_theme(parse_theme_cached(theme_path(name)))
        if self.theme["error"]:
            msg = "Error in file: " + self.theme["error"]
        else:
            msg = "%s  (colors read: %d/%d)" % (name, self.theme["found"], len(COLOR_PATHS))
            msg += "  - style: %s" % ("motif (raised)" if self.theme["win_deco"] == "motif"
                                     else "flat")
            if self.theme["note"]:
                msg += " - " + self.theme["note"]
        self.set_status(msg)
        if self.section == "background":
            self.load_background_controls()
        self.draw()

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
        self.draw()

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
            rgb = self._rgb(color)
            fg = "#000000" if rgb and sum(rgb) / 3 > 127 else "#ffffff"
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
            new = rewrite_background(data, mode, c1, c2)
            shutil.copy2(path, path + ".bak")
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            _PARSE_CACHE.pop(path, None)
            self._set_theme(parse_theme(path))
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
        """Solid rectangle or gradient between two colors. A gradient only needs as
        many bands as the colors have distinct steps, so it uses few canvas items."""
        c = self.canvas
        c1, c2 = spec
        if not c2:
            c.create_rectangle(x1, y1, x2, y2, fill=c1, outline=outline)
            return
        a, b = self._rgb(c1), self._rgb(c2)
        length = (y2 - y1) if vertical else (x2 - x1)
        delta = max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))
        steps = int(max(2, min(length, delta + 1, 64)))
        for i in range(steps):
            f = i / (steps - 1)
            col = "#%02x%02x%02x" % (int(a[0] + (b[0] - a[0]) * f), int(a[1] + (b[1] - a[1]) * f),
                                     int(a[2] + (b[2] - a[2]) * f))
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

    def _edges(self, base):
        """(light, dark) bevel edges of a color. Measured on a real JWM motif theme:
        JWM multiplies each channel by about 1.447 (light) and 0.55 (dark)."""
        e = self._edge_cache.get(base)
        if e is None:
            r, g, b = self._rgb(base)
            e = (("#%02x%02x%02x" % tuple(min(255, int(v * 1.447)) for v in (r, g, b))),
                 ("#%02x%02x%02x" % tuple(int(v * 0.55) for v in (r, g, b))))
            self._edge_cache[base] = e
        return e

    def _bevel(self, x1, y1, x2, y2, base, raised=True, width=1):
        """Raised or sunken bevel, Motif / Windows 98 style."""
        c = self.canvas
        light, dark = self._edges(base)
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
                    resample = Image.Resampling.BICUBIC
                except AttributeError:
                    resample = Image.BICUBIC
                scale = size / float(max(im.width, im.height))   # JWM also enlarges small icons
                im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                               resample)
                img = ImageTk.PhotoImage(im, master=self)
            except Exception:
                try:  # without Pillow: Tk only reads png/gif/ppm
                    raw = tk.PhotoImage(file=path, master=self)
                    big = max(raw.width(), raw.height())
                    if big >= size:
                        f = max(1, -(-big // size))
                        img = raw.subsample(f) if f > 1 else raw
                    else:
                        img = raw.zoom(max(1, size // big))
                except Exception:
                    img = None
        cache[key] = img
        return img

    def _icon_font(self, tray_font):
        """Find an installed Nerd Font (preferring the tray one)."""
        if tray_font not in self._font_memo:
            self._font_memo[tray_font] = self._find_icon_font(self._families(), tray_font)
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

    def _set_theme(self, theme):
        if theme is not self.theme:
            self.theme = theme
            self._theme_rev += 1         # tells draw() that the picture is out of date

    def _bg_state(self):
        return (self.bg_default.get(), self.bg_mode.get(),
                self.bg_color1.get(), self.bg_color2.get())

    def draw(self, force=False):
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 300 or h < 200:
            return
        # Nothing to do if what the picture depends on has not changed.
        key = (self._theme_rev, w, h, self.section,
               self._bg_state() if self.section == "background" else None)
        if key == self._drawn_key and not force:
            return
        self._drawn_key = key
        c.delete("all")
        raw = self.theme
        if not raw:
            return
        if self.section == "background":
            self.draw_background_preview(w, h)
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

        self._fill(0, 0, w, h, S("desktop"), vertical=True)     # desktop background

        bw = raw["border"]
        th = raw["title_h"]

        def glyphs(cx, cy, r, kind, color, thick):
            """Window button symbols: close (X), maximize (square), minimize (dash)."""
            if kind == "close":
                c.create_line(cx - r, cy - r, cx + r + 1, cy + r + 1, fill=color, width=thick)
                c.create_line(cx - r, cy + r, cx + r + 1, cy - r - 1, fill=color, width=thick)
            elif kind == "max":
                c.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline=color, width=thick)
            else:
                c.create_line(cx - r, cy + r - 1, cx + r + 1, cy + r - 1, fill=color, width=2)

        def motif_window(x, y, ww, hh, pre, label, bold):
            """Motif frame, reproduced from a real JWM window (pixel measurements):
            ring 0 = raised bevel, ring 1 = dark line, then the title bar made of four
            raised cells (title + three square buttons) above the client area."""
            base, txt = C(pre + "_title"), C(pre + "_text")
            ring = 2
            c.create_rectangle(x, y, x + ww, y + hh, fill=self._edges(base)[1], outline="")
            self._bevel(x, y, x + ww, y + hh, base, True, 1)
            tx1, ty1, tx2 = x + ring, y + ring, x + ww - ring
            ty2 = ty1 + th
            c.create_rectangle(tx1, ty2, tx2, y + hh - ring, fill="#1e1e1e", outline="")
            self._fill(tx1, ty1, tx2, ty2, S(pre + "_title"))
            cy = ty1 + th / 2
            self._bevel(tx1, ty1, tx2 - 3 * th, ty2, base, True, 1)       # title cell
            c.create_text(tx1 + 8, cy, text=label, anchor="w", fill=txt, font=F(9, bold))
            r = max(4, int(th * 0.22))
            for i, kind in enumerate(("close", "max", "min")):           # right to left
                bx2 = tx2 - i * th
                bx1 = bx2 - th
                self._bevel(bx1, ty1, bx2, ty2, base, True, 1)           # raised button
                glyphs((bx1 + bx2) / 2, cy, r, kind, txt, 2)
            c.create_text(tx1 + 10, ty2 + 18, text="Window content", anchor="w",
                          fill="#9a9a9a", font=F(9))

        def flat_window(x, y, ww, hh, pre, label, bold):
            """Flat frame: Outline color border, symbols without boxes."""
            txt = C(pre + "_text")
            c.create_rectangle(x, y, x + ww, y + hh, fill=C(pre + "_outline"), outline="")
            self._fill(x + bw, y + bw, x + ww - bw, y + bw + th, S(pre + "_title"))
            c.create_rectangle(x + bw, y + bw + th, x + ww - bw, y + hh - bw,
                               fill="#1e1e1e", outline="")
            cy = y + bw + th / 2
            c.create_text(x + bw + 8, cy, text=label, anchor="w", fill=txt, font=F(9, bold))
            r = max(4, int(th * 0.22))
            cx = x + ww - bw - 14
            for kind in ("close", "max", "min"):                         # right to left
                glyphs(cx, cy, r, kind, txt, 1)
                cx -= 20
            c.create_text(x + bw + 10, y + bw + th + 18, text="Window content",
                          anchor="w", fill="#9a9a9a", font=F(9))

        def window(x, y, ww, hh, active, label):
            pre = "act" if active else "inact"
            x, y, ww, hh = int(x), int(y), int(ww), int(hh)
            if raw["win_deco"] == "motif":
                motif_window(x, y, ww, hh, pre, label, active)
            else:
                flat_window(x, y, ww, hh, pre, label, active)

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
        # Shared tray renderer used by both the Themes and the Background previews.
        # Elements are drawn in the order of the theme's <Tray> section.
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

        logo = self._logo_image(raw["icon_paths"], tray_h - 3)
        icon_fam = self._icon_font(raw["tray_font"])
        is_pua = lambda ch: 0xE000 <= ord(ch) <= 0xF8FF or ord(ch) >= 0xF0000

        def label_of(text):
            lab = text.strip()
            if lab and any(is_pua(ch) for ch in lab) and not icon_fam:
                return "\u2022"                  # Nerd Font symbol not available
            return lab

        ndesk, cell = 3, int(tray_h * 1.64)

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
                    return int(tray_h * 1.64)
                lab = label_of(it["label"])
                if not lab:
                    return tray_h
                if any(is_pua(ch) for ch in it["label"]):
                    return max(tray_h, 12 + 7 * len(lab))     # symbol buttons
                return 6 + 7 * len(lab)                       # plain text, e.g. "_" is 13 px
            return 0                              # tasklist: takes the remaining space

        items = raw["tray_items"]
        flex = max(90, w - sum(width_of(i) for i in items))
        x = 0
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
                    x0, act = x + i * cell, i == 1       # like the real tray: 2nd desktop active
                    left = x0 + 1 if (tmotif and i) else x0
                    self._fill(left, y1, x0 + cell, y2, S("pager_act_bg") if act else S("pager_bg"))
                    if act:  # thumbnail of the active window on the active desktop
                        c.create_rectangle(x0 + 4, y1 + 6, x0 + 26, y2 - 4,
                                           fill=C("pager_act_fg"), outline=C("pager_outline"))
                    elif it.get("labeled"):
                        c.create_text(x0 + cell / 2, mid, text=str(i + 1),
                                      fill=C("pager_text"), font=F(8))
                    if tmotif:   # thin line between desktops, in the pager outline color
                        if i:
                            c.create_line(x0, y1, x0, y2, fill=C("pager_outline"))
                    else:
                        c.create_rectangle(x0, y1, x0 + cell, y2, outline=C("pager_outline"))
            elif kind == "tasklist":
                kinds = (("Active window", "task_act_", True), ("Window", "task_", False),
                         ("Minimized", "task_min_", True))
                n = max(1, min(len(kinds), int(wd // 90)))
                iw = max(50, min(it["maxwidth"], int(wd // n)))
                for j, (label, pre, pressed) in enumerate(kinds[:n]):
                    ix = x + j * iw                  # items are side by side, no gap
                    tbtn(ix, y1, ix + iw, y2, S(pre + "bg"), pressed=pressed)
                    c.create_rectangle(ix + 5, mid - 5, ix + 15, mid + 5, outline=C(pre + "fg"))
                    room = max(1, (iw - 26) // 6)           # keep the text inside its item
                    shown = label if len(label) <= room else label[:max(1, room - 1)] + "\u2026"
                    c.create_text(ix + 21, mid, text=shown, anchor="w", fill=C(pre + "fg"),
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
                pass     # JWM fills the Dock at runtime; its space stays empty in the preview
            elif kind == "clock":
                if "clock_bg" in col:
                    self._fill(x, y1, x + wd, y2, S("clock_bg"))
                c.create_text(x + wd / 2, mid, text=self._clock_text(it["format"]),
                              fill=C("clock_fg"), font=F(9))
            x += wd


if __name__ == "__main__":
    App().mainloop()
