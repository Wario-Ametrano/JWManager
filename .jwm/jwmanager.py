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
import base64
import colorsys
import filecmp
import glob
import io
import json
import locale
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog
import xml.etree.ElementTree as ET

APP_NAME = "JWManager"      # window title and WM class

HOME = os.path.expanduser("~")
JWM_DIR = os.path.join(HOME, ".jwm")
THEMES_DIR = os.path.join(JWM_DIR, "themes")
TARGET = os.path.join(HOME, ".jwmrc")
ICONS_DIR = os.path.join(JWM_DIR, "icons")           # one folder per icon set
DEFAULT_ICON_SET = "Default"                         # = the icons the theme file already uses
DEFAULT_FONT_SPEC = "Sans-12"                        # used when a style has no <Font>
THEME_FILE = ".jwmrc"
DEFAULT_NAME = "Default"
SYSTEM_RC = "/etc/jwm/system.jwmrc"
ICON_FILE = os.path.join(JWM_DIR, "jwmanager.png")            # the only icon used
CACHE_FILE = os.path.join(JWM_DIR, "jwmanager-cache.json")    # remembers the logo path

# Wallpapers: JWM draws no images itself, so an external script sets them (feh and friends).
WALLPAPER_SCRIPT = os.path.join(JWM_DIR, "jwmanager-wallpaper.sh")
WALLPAPER_MODES = (("tiled", "Set Tiled"), ("scaled", "Set Scaled"),
                   ("centered", "Set Centered"), ("filled", "Set Filled"))
IMAGE_EXT = (".png", ".jpg", ".jpeg")

BEVEL = 2     # width of the raised / sunken bevels of the app's own buttons and fields

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


def _prepared_text(path):
    """File text with the things a strict XML parser rejects fixed (see read_xml)."""
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)       # comments
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)           # xml declaration
    text = _TAG.sub(lambda m: _ATTR_GAP.sub(r"\1 ", m.group(0)), text)
    return _ENTITY_BAD.sub("&amp;", text)


def read_xml(path):
    """Read a .jwmrc tolerantly.

    JWM accepts files that a strict XML parser rejects, for example
    unescaped '&' in text or attributes without a space (x="0"y="-1").
    We fix those before parsing the file.
    """
    return ET.fromstring(_prepared_text(path))


def read_xml_fragment(path):
    """Like read_xml, but also accepts files with several top-level elements
    (e.g. /etc/jwm/debian-menu): they are wrapped in a <JWM> element."""
    text = _prepared_text(path)
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        return ET.fromstring("<JWM>" + text + "</JWM>")


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
    "desktop": [".//Desktops/Background", ".//Desktops/Desktop/Background"],
    "tray_bg": ["TrayStyle/Background"],
    "tray_fg": ["TrayStyle/Foreground", "TrayStyle/Text"],
    "tray_outline": ["TrayStyle/Outline"],
    "tbtn_bg": ["TrayButtonStyle/Background"],
    "tbtn_fg": ["TrayButtonStyle/Foreground", "TrayButtonStyle/Text"],
    "tbtn_act_bg": ["TrayButtonStyle/Active/Background"],
    "tbtn_act_fg": ["TrayButtonStyle/Active/Foreground", "TrayButtonStyle/Active/Text"],
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
    "tbtn_bg": "tray_bg", "tbtn_fg": "tray_fg", "tbtn_act_bg": "tray_act_bg",
    "tbtn_act_fg": "tray_act_fg",
    "act_outline": "act_title", "inact_outline": "inact_title",
    "menu_outline": "menu_bg", "menu_sel_bg": "menu_fg", "menu_sel_fg": "menu_bg",
    "task_bg": "tray_bg", "task_fg": "tray_fg",
    "task_act_bg": "task_bg", "task_act_fg": "task_fg",
    "task_min_bg": "task_bg", "task_min_fg": "task_fg",
    "clock_bg": "tray_bg", "clock_fg": "tray_fg",
    "pager_bg": "tray_bg", "pager_fg": "tray_fg", "pager_outline": "tray_bg",
    "pager_text": "tray_fg", "pager_act_bg": "pager_fg", "pager_act_fg": "pager_bg",
}


def parse_wallpaper_command(text):
    """'sh /x/jwmanager-wallpaper.sh MODE FILE' -> (MODE, FILE), or None."""
    try:
        parts = shlex.split(text)
    except ValueError:
        return None
    script = os.path.basename(WALLPAPER_SCRIPT)
    for i, part in enumerate(parts):
        if os.path.basename(part) == script and len(parts) > i + 2:
            return parts[i + 1], parts[i + 2]
    return None


def parse_theme(path):
    """Extract the main colors and measures from a .jwmrc (JWM 2.3 and 2.4 formats)."""
    t = {"tray_pos": "bottom", "tray_h": 28, "title_h": 22, "border": 1,
         "font": "", "tray_font": "", "icon_paths": [], "note": "",
         "fonts": {}, "icon_set": DEFAULT_ICON_SET, "icon_default_paths": None,
         "menu_items": [], "menu_includes": [],
         "win_deco": "flat", "tray_deco": "flat", "menu_deco": "flat", "wallpaper": None,
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

    for root in roots:                           # wallpaper set through our script?
        for el in root.iter("StartupCommand"):
            wallpaper = parse_wallpaper_command(el.text or "")
            if wallpaper:
                t["wallpaper"] = wallpaper
                break
        if t["wallpaper"]:
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

    for key, tag in (("window", "WindowStyle"), ("menu", "MenuStyle"), ("tray", "TrayStyle"),
                     ("task", "TaskListStyle"), ("pager", "PagerStyle"), ("clock", "ClockStyle")):
        for root in roots:                       # one font per kind of element
            v = text_of(root.find(tag + "/Font"))
            if v:
                t["fonts"][key] = v
                break

    t["icon_set"] = icon_set_of(t["icon_paths"])
    try:                                         # icons the theme had before we changed them
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            block = _ICONS_BLOCK_RE.search(f.read())
        if block:
            t["icon_default_paths"] = list_icon_paths_in_text(block.group(1))
    except OSError:
        pass
    t["menu_items"] = parse_menu(roots)
    for root in roots:                           # files the RootMenu includes
        menu = root.find("RootMenu")
        if menu is not None:
            for inc in menu.iter("Include"):
                target = os.path.expanduser((inc.text or "").strip())
                if target and not target.startswith("exec:"):
                    t["menu_includes"].append(target)

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
    mode "image": no <Background> at all (an external script paints the wallpaper).
    mode "default": go back to the original background (or none)."""
    found = _find_active_background(data)
    has_marker = bool(_DEFAULT_BG_MARK.search(data))
    if mode == "image":
        # JWM must not paint over the wallpaper: take the <Background> out, but keep it
        # in the "default" comment so that "Use JWM Default Background" can bring it back.
        if found:
            s, e, old = found
            repl = "" if has_marker else "<!-- JWManager default background: " + old + " -->"
            data = data[:s] + repl + data[e:]
        return data
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


# ------------------------------------------------------------ wallpaper (image) support
_WP_BLOCK = re.compile(
    r"[ \t]*<!-- JWManager wallpaper begin -->.*?<!-- JWManager wallpaper end -->[ \t]*\n?", re.S)


def wallpaper_command(mode, file):
    return "sh %s %s %s" % (shlex.quote(WALLPAPER_SCRIPT), mode, shlex.quote(file))


def rewrite_wallpaper(data, mode=None, file=None):
    """Remove the wallpaper commands JWManager put in a theme and, if mode and file are given,
    add new ones: the script runs when JWM starts and every time JWM restarts."""
    data = _WP_BLOCK.sub("", data)
    if not mode:
        return data
    cmd = wallpaper_command(mode, file).replace("&", "&amp;").replace("<", "&lt;") \
                                       .replace(">", "&gt;")
    block = ("  <!-- JWManager wallpaper begin -->\n"
             "  <StartupCommand>%s</StartupCommand>\n"
             "  <RestartCommand>%s</RestartCommand>\n"
             "  <!-- JWManager wallpaper end -->\n") % (cmd, cmd)
    end = data.rfind("</JWM>")
    return data + "\n" + block if end < 0 else data[:end] + block + data[end:]


_PIL = {}


def pil_modules():
    """Pillow is optional: it is only needed to preview wallpapers."""
    if not _PIL:
        try:
            from PIL import Image
            _PIL["Image"] = Image
        except Exception:
            _PIL["Image"] = None
        try:
            from PIL import ImageTk
            _PIL["ImageTk"] = ImageTk
        except Exception:
            _PIL["ImageTk"] = None
    return _PIL


def render_wallpaper(path, mode, w, h, screen_w, screen_h):
    """PIL image (w x h) of the wallpaper as feh paints it. The preview shows the screen
    scaled down by w / screen_w, so tiled and centered images keep their real proportions."""
    Image = pil_modules()["Image"]
    im = Image.open(path).convert("RGB")
    f = w / float(max(1, screen_w))

    def resized(width, height):
        size = (max(4, int(width)), max(4, int(height)))
        k = int(min(im.width / float(size[0]), im.height / float(size[1])))
        src = im.reduce(k) if k >= 2 else im          # fast pre-shrink for big pictures
        return src.resize(size, Image.BILINEAR)

    if mode == "scaled":                              # stretched to the whole screen
        return resized(w, h)
    if mode == "filled":                              # keeps proportions, fills, crops the rest
        k = max(w / float(im.width), h / float(im.height))
        big = resized(im.width * k, im.height * k)
        left, top = (big.width - w) // 2, (big.height - h) // 2
        return big.crop((left, top, left + w, top + h))
    out = Image.new("RGB", (w, h), (0, 0, 0))
    small = resized(im.width * f, im.height * f)
    if mode == "centered":
        out.paste(small, ((w - small.width) // 2, (h - small.height) // 2))
    else:                                             # tiled
        for y in range(0, h, small.height):
            for x in range(0, w, small.width):
                out.paste(small, (x, y))
    return out


# ------------------------------------------------------------ fonts, menu and icons (preview data)
def parse_font(spec):
    """JWM / fontconfig font name -> (family, pixel size, bold, italic).
    Understands 'Sans-12', 'Sans-12:bold', 'Sans:size=12:bold', 'Sans:pixelsize=14'.
    Point sizes are turned into pixels at 96 dpi, like JWM does."""
    spec = (spec or "").strip() or DEFAULT_FONT_SPEC
    head, _, opts = spec.partition(":")
    family, points, pixels = head.strip(), 12.0, None
    m = re.match(r"^(.*?)-(\d+(?:\.\d+)?)$", head.strip())
    if m:
        family, points = m.group(1).strip(), float(m.group(2))
    bold = italic = False
    for opt in opts.split(":"):
        o = opt.strip().lower()
        try:
            if o in ("bold", "weight=bold", "weight=200", "weight=demibold"):
                bold = True
            elif o in ("italic", "oblique", "slant=italic", "slant=100", "slant=oblique"):
                italic = True
            elif o.startswith("size="):
                points = float(o[5:])
            elif o.startswith("pixelsize="):
                pixels = float(o[10:])
        except ValueError:
            pass
    px = pixels if pixels else points * 96.0 / 72.0
    return family or "Sans", max(7, int(round(px))), bold, italic


MENU_LIMIT = 16
# The preview menu is read from this file, whatever the theme is (JWM themes <Include> it).
MENU_FILES = (os.path.join(JWM_DIR, "jwm_menu"), os.path.join(HOME, ".jwm_menu"),
              os.path.join(JWM_DIR, "menu"), os.path.join(HOME, ".debian-menu"))
# Fixed size of the preview menu: it never changes with the theme (a scaled-down JWM menu).
PV_MENU_ITEM_H, PV_MENU_ICON, PV_MENU_FONT_PX, PV_MENU_SEP_H = 21, 17, 12, 6
def _menu_entries(el, depth=0):
    """Top-level entries of a menu element, with <Include> files expanded."""
    entries = []
    for child in el:
        tag = child.tag
        if tag == "Include":
            target = os.path.expanduser((child.text or "").strip())
            if not target or target.startswith("exec:") or depth > 2:
                continue                           # commands are never run for a preview
            try:
                inc = read_xml_fragment(target)
            except Exception:
                continue
            holder = ET.Element("holder")
            holder.extend(list(inc) if inc.tag in ("JWM", "RootMenu") else [inc])
            entries += _menu_entries(holder, depth + 1)
        elif tag == "Menu":
            entries.append({"type": "menu", "label": child.get("label") or "",
                            "icon": child.get("icon") or ""})
        elif tag == "Separator":
            entries.append({"type": "separator", "label": "", "icon": ""})
        elif tag in ("Program", "Restart", "Exit"):
            label = child.get("label") or (child.text or "").strip() if tag == "Program" \
                else (child.get("label") or tag)
            entries.append({"type": "item", "label": label or tag,
                            "icon": child.get("icon") or ""})
        elif tag == "Desktops":
            entries.append({"type": "menu", "label": child.get("label") or "Desktops",
                            "icon": child.get("icon") or ""})
    return entries


def parse_menu(roots):
    """Entries of the theme's <RootMenu>: [{'type','label','icon'}, ...]."""
    for root in roots:
        menu = root.find("RootMenu")
        if menu is not None:
            return _menu_entries(menu)[:MENU_LIMIT]
    return []


_SVG_TOOLS = []
SVG_NOTE = {"black": False}      # set when the only renderer available draws black silhouettes


def svg_tools():
    """svg renderers installed, best first. ImageMagick is last: without the rsvg delegate it
    draws gradients and many icons as black silhouettes."""
    if not _SVG_TOOLS:
        try:
            import cairosvg  # noqa: F401
            _SVG_TOOLS.append("cairosvg")
        except Exception:
            pass
        for exe in ("rsvg-convert", "resvg"):
            if shutil.which(exe):
                _SVG_TOOLS.append(exe)
        for exe in ("magick", "convert"):
            if shutil.which(exe):
                _SVG_TOOLS.append(exe)
                break
        if not _SVG_TOOLS:
            _SVG_TOOLS.append("")                         # remember that there is none
    return [t for t in _SVG_TOOLS if t]


def _render_svg(tool, path, size):
    try:
        if tool == "cairosvg":
            import cairosvg
            return cairosvg.svg2png(url=path, output_width=size, output_height=size)
        if tool == "rsvg-convert":
            cmd = ["rsvg-convert", "-w", str(size), "-h", str(size), "--keep-aspect-ratio", path]
        elif tool == "resvg":
            cmd = ["resvg", "-w", str(size), "-h", str(size), path, "-c"]
        else:                                             # magick / convert
            cmd = [tool, "-background", "none", "-density", "384", "-resize",
                   "%dx%d" % (size, size), "svg:" + path, "png:-"]
        out = subprocess.run(cmd, capture_output=True, timeout=8)
        if out.returncode == 0 and out.stdout[:4] == b"\x89PNG":
            return out.stdout
    except Exception:
        pass
    return None


def opaque_brightness(im):
    """Mean brightness (0-255) of the visible pixels of an image, or None if there are none."""
    small = im.convert("RGBA").resize((24, 24))
    total = count = 0
    for r, g, b, a in small.getdata():
        if a > 128:
            total += (r + g + b) / 3.0
            count += 1
    return total / count if count >= 8 else None


def svg_to_png(path, size):
    """PNG bytes of an svg icon. Renderers are tried in turn and a result that is an all-black
    silhouette is rejected in favour of the next one (only the last resort may stay black)."""
    Image = pil_modules()["Image"]
    last = None
    for tool in svg_tools():
        data = _render_svg(tool, path, size)
        if not data:
            continue
        last = data
        if Image is None:
            return data
        try:
            brightness = opaque_brightness(Image.open(io.BytesIO(data)))
        except Exception:
            return data
        if brightness is None or brightness > 14:
            SVG_NOTE["black"] = False
            return data
        SVG_NOTE["black"] = True                          # looks black: try the next tool
    return last


ICON_EXT = ("", ".png", ".xpm", ".jpg", ".jpeg", ".gif", ".bmp", ".svg")   # svg comes last
_ICON_MEMO = {}


def find_icon(name, paths):
    """File JWM would use for icon="name": an absolute path, or the name searched in every
    <IconPath> in order (a missing extension is guessed)."""
    if not name:
        return None
    key = (name, tuple(paths))
    if key in _ICON_MEMO:
        return _ICON_MEMO[key]
    bases = [name] if os.path.isabs(name) else [os.path.join(os.path.expanduser(d), name)
                                                for d in paths]
    found = None
    for base in bases:
        for ext in ICON_EXT:
            if os.path.isfile(base + ext):
                found = base + ext
                break
        if found:
            break
    _ICON_MEMO[key] = found
    return found


# icon sets: one folder per set inside ~/.jwm/icons; a theme uses one with <IconPath>
_ICONPATH_RE = re.compile(r"[ \t]*<IconPath>([^<]*)</IconPath>[ \t]*\n?")
_ICONS_BLOCK_RE = re.compile(
    r"[ \t]*<!-- JWManager default icons begin\n(.*?)JWManager default icons end -->[ \t]*\n?", re.S)
_ICONS_OURS_RE = re.compile(r"[ \t]*<IconPath>[^<]*</IconPath><!-- JWManager icons -->[ \t]*\n?")


def icon_set_path(name):
    return os.path.join(ICONS_DIR, name)


def list_icon_sets():
    """['Default', <one entry per folder in ~/.jwm/icons>]. 'Default' always comes first and
    means: the icons the theme file already uses."""
    sets = []
    try:
        for name in sorted(os.listdir(ICONS_DIR), key=str.lower):
            if name.lower() != DEFAULT_ICON_SET.lower() and os.path.isdir(icon_set_path(name)):
                sets.append(name)
    except OSError:
        pass
    return [DEFAULT_ICON_SET] + sets


def icon_set_of(paths):
    """Name of the icon set a list of <IconPath> values points to ('Default' if none)."""
    icons = os.path.normpath(ICONS_DIR)
    for p in paths:
        q = os.path.normpath(os.path.expanduser(p))
        if os.path.dirname(q) == icons and os.path.basename(q):
            return os.path.basename(q)
    return DEFAULT_ICON_SET


def list_icon_paths_in_text(text):
    return [x.strip() for x in re.findall(r"<IconPath>([^<]*)</IconPath>", text)]


def _in_comment(data, pos):
    return data.rfind("<!--", 0, pos) > data.rfind("-->", 0, pos)


def rewrite_icons(data, name):
    """Return the theme text using the icon set `name` (a folder of ~/.jwm/icons).

    The <IconPath> lines the theme had are kept inside a comment (all of them, so there is
    no conflict between sets) and a single new line points to the chosen set.
    name None / "Default": remove the new line and bring the original lines back."""
    block = _ICONS_BLOCK_RE.search(data)
    stored = block.group(1) if block else None
    data = _ICONS_OURS_RE.sub("", data)                   # our line is always rebuilt
    block = _ICONS_BLOCK_RE.search(data)
    active = [m for m in _ICONPATH_RE.finditer(data) if not _in_comment(data, m.start())]

    if name in (None, "", DEFAULT_ICON_SET):
        if stored is not None:                            # bring the standard lines back
            return data[:block.start()] + stored + data[block.end():]
        sets = [m for m in active
                if icon_set_of([m.group(1).strip()]) != DEFAULT_ICON_SET]
        if len({m.group(1).strip() for m in sets}) >= 2:  # several sets in one theme = conflict
            first = sets[0]
            keep = ""
            if os.path.isdir(icon_set_path(DEFAULT_ICON_SET)):
                keep = "    <IconPath>%s</IconPath>\n" % icon_set_path(DEFAULT_ICON_SET)
            else:
                keep = first.group(0)
            for m in reversed(sets):
                data = data[:m.start()] + (keep if m is first else "") + data[m.end():]
        return data

    new_line = "<IconPath>%s</IconPath><!-- JWManager icons -->\n" % icon_set_path(name)
    if stored is None and len(active) == 1 and \
            os.path.normpath(os.path.expanduser(active[0].group(1).strip())) == \
            os.path.normpath(icon_set_path(name)):
        return data                                       # the theme already uses this set
    extra = "".join(m.group(0) for m in active)           # lines to move into the comment
    indent = re.match(r"[ \t]*", active[0].group(0)).group(0) if active else "    "
    for m in reversed(active):
        data = data[:m.start()] + data[m.end():]
    if block is not None:                                 # keep the stored originals
        block = _ICONS_BLOCK_RE.search(data)
        text = stored + (extra if extra.endswith("\n") or not extra else extra + "\n")
        head = data[:block.start()] + indent + "<!-- JWManager default icons begin\n" + text + \
            "JWManager default icons end -->\n"
        return head + indent + new_line + data[block.end():]
    end = data.rfind("</JWM>")
    pos = active[0].start() if active else (end if end >= 0 else len(data))
    if extra and not extra.endswith("\n"):
        extra += "\n"
    insert = indent + "<!-- JWManager default icons begin\n" + extra + \
        "JWManager default icons end -->\n" + indent + new_line
    return data[:pos] + insert + data[pos:]


# -------------------------------------------------------------------- custom widgets
# The app draws its own buttons, radio buttons, fields and sliders so that they look like the
# JWM panel of the applied theme: only two states (normal and pressed), no hover effect, and the
# text never moves.
_HEX6 = re.compile(r"^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$")


class Bevel(tk.Frame):
    """A frame with a raised or sunken bevel made of thin lines. Put the content in .inner."""

    def __init__(self, master, app, sunken=True, **kw):
        super().__init__(master, bd=0, highlightthickness=0, **kw)
        self.app, self.sunken = app, sunken
        self.inner_color = None                  # None = the panel background
        self._lines = [tk.Frame(self, bd=0, highlightthickness=0) for _ in range(4)]
        self.inner = tk.Frame(self, bd=0, highlightthickness=0)
        self._bw = 0
        app._custom.append(self)
        self.restyle()

    def restyle(self):
        p = self.app.pal
        bw = BEVEL if p["motif"] else 1
        if p["motif"]:
            light, dark = self.app._edges(p["bg"])
            tl, br = (dark, light) if self.sunken else (light, dark)
        else:
            tl = br = p["edge"]
        top, left, bottom, right = self._lines
        top.configure(bg=tl)
        left.configure(bg=tl)
        bottom.configure(bg=br)
        right.configure(bg=br)
        self.inner.configure(bg=self.inner_color or p["bg"])
        if bw != self._bw:                       # (re)place the four lines and the content
            self._bw = bw
            top.place(x=0, y=0, relwidth=1, height=bw)
            left.place(x=0, y=0, relheight=1, width=bw)
            bottom.place(x=0, rely=1, y=-bw, relwidth=1, height=bw)
            right.place(relx=1, x=-bw, y=0, relheight=1, width=bw)
            self.inner.place(x=bw, y=bw, relwidth=1, relheight=1, width=-2 * bw, height=-2 * bw)

    def set_inner_color(self, color):
        self.inner_color = color
        self.inner.configure(bg=color)


class ThemeButton(tk.Canvas):
    """Button with the look of a JWM panel button: raised, or pressed (sunken). No hover state."""

    def __init__(self, master, app, text, command, height=30):
        super().__init__(master, width=app.ui_font.measure(text) + 20, height=height,
                         bd=0, highlightthickness=0, cursor="hand2")
        self.app, self.text, self.on_click = app, text, command
        self.selected = False                    # a selected tab stays pressed in
        self._down = False
        app._custom.append(self)
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Leave>", self._leave)

    def set_text(self, text):
        self.text = text
        self.redraw()

    def set_selected(self, value):
        if value != self.selected:
            self.selected = value
            self.redraw()

    def _press(self, event):
        self._down = True
        self.redraw()

    def _release(self, event):
        was_down, self._down = self._down, False
        self.redraw()
        if was_down and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.on_click()

    def _leave(self, event):
        if self._down:                           # moved away while pressed: cancel
            self._down = False
            self.redraw()

    def restyle(self):
        self.redraw()

    def redraw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        app, p = self.app, self.app.pal
        if self.selected:                        # like the active window button of the panel
            bg, fg, sunk = p["tab_bg"], p["tab_fg"], True
        elif self._down:
            bg, fg, sunk = p["act_bg"], p["act_fg"], True
        else:
            bg, fg, sunk = p["btn_bg"], p["btn_fg"], False
        self.delete("all")
        self.create_rectangle(0, 0, w, h, fill=bg, outline="")
        if p["motif"]:
            app._bevel(0, 0, w, h, bg, not sunk, BEVEL, canvas=self)
        else:
            self.create_rectangle(0, 0, w - 1, h - 1,
                                  outline=p["tab_fg"] if self.selected else p["edge"])
        self.create_text(w // 2, h // 2, text=self.text, fill=fg, font=app.ui_font)


class ThemeRadio(tk.Canvas):
    """Radio button: round indicator and text, bound to a StringVar."""

    def __init__(self, master, app, text, variable, value, command):
        super().__init__(master, width=10, height=22, bd=0, highlightthickness=0, cursor="hand2")
        self.app, self.text, self.variable, self.value, self.on_click = (
            app, text, variable, value, command)
        app._custom.append(self)
        variable.trace_add("write", lambda *a: self.redraw())
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<ButtonRelease-1>", self._click)

    def _click(self, event):
        self.variable.set(self.value)
        self.on_click()

    def restyle(self):
        self.redraw()

    def redraw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        p = self.app.pal
        self.delete("all")
        self.create_rectangle(0, 0, w, h, fill=p["bg"], outline="")
        cy = h // 2
        self.create_oval(1, cy - 5, 12, cy + 5, fill=p["btn_bg"], outline=p["muted"])
        if self.variable.get() == self.value:
            self.create_oval(4, cy - 2, 9, cy + 3, fill=p["fg"], outline=p["fg"])
        self.create_text(22, cy, text=self.text, anchor="w", fill=p["fg"], font=self.app.ui_font)


class Bar(tk.Canvas):
    """Horizontal slider drawn as a color gradient, with a triangle marker below it."""
    BAR_H, HEIGHT, STEP = 8, 19, 4

    def __init__(self, master, app, on_change):
        super().__init__(master, width=10, height=self.HEIGHT, bd=0, highlightthickness=0,
                         cursor="hand2")
        self.app, self.on_change = app, on_change
        self.value = 0.0
        self.color_at = lambda frac: "#808080"   # gradient: fraction -> color
        self._rects, self._bar_w, self._marker = [], 0, None
        app._custom.append(self)
        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)

    def _on_resize(self, event):
        if event.width != self._bar_w:
            self._bar_w = event.width
            self._build()

    def _build(self):
        self.delete("all")
        w = self._bar_w
        n = max(2, w // self.STEP + 1)
        self._rects = [self.create_rectangle(i * self.STEP, 0, (i + 1) * self.STEP + 1,
                                             self.BAR_H, outline="", fill="#808080")
                       for i in range(n)]
        self._marker = self.create_polygon(0, 0, 0, 0, 0, 0, outline="")
        self.recolor()
        self._place_marker()

    def recolor(self):
        n = len(self._rects)
        for i, rid in enumerate(self._rects):
            self.itemconfigure(rid, fill=self.color_at((i + 0.5) / n))

    def set_value(self, value):
        self.value = min(1.0, max(0.0, value))
        self._place_marker()

    def _place_marker(self):
        if self._marker is None or self._bar_w < 4:
            return
        p = self.app.pal
        x = self.value * (self._bar_w - 1)
        self.coords(self._marker, x, self.BAR_H + 2, x - 4, self.HEIGHT - 1, x + 4, self.HEIGHT - 1)
        self.itemconfigure(self._marker, fill=p["fg"], outline=p["bg"])

    def _drag(self, event):
        if self._bar_w > 1:
            self.set_value(event.x / float(self._bar_w - 1))
            self.on_change(self.value)

    def restyle(self):
        self.configure(bg=self.app.pal["bg"])
        self._place_marker()


class ColorPicker(tk.Frame):
    """Hex field + color swatch + three sliders (lightness, hue, saturation).
    The color is kept as HSL, so dragging one slider never changes the others."""

    def __init__(self, master, app, label, variable, on_change):
        super().__init__(master, bd=0, highlightthickness=0)
        self.app, self.var, self.on_change = app, variable, on_change
        self.h, self.l, self.s = 0.6, 0.5, 0.5
        app._frames.append(self)
        row = app._frame(self)
        row.pack(fill="x")
        box = app._frame(row, width=51, height=28)
        box.pack_propagate(False)
        box.pack(side="left")
        self.label = app._label(box, text=label)
        self.label.pack(fill="both", expand=True)
        field = Bevel(row, app, width=79, height=28)
        field.pack_propagate(False)
        field.pack(side="left")
        self.entry = tk.Entry(field.inner, relief="flat", bd=0, highlightthickness=0,
                              font=app.ui_font, width=8)
        self.entry.pack(fill="both", expand=True, padx=6)
        self.entry.bind("<Return>", lambda e: self._commit())
        self.entry.bind("<FocusOut>", lambda e: self._commit())
        self.entry.bind("<KeyRelease>", self._typing)
        self.swatch = Bevel(row, app, height=28)
        self.swatch.pack(side="left", fill="x", expand=True, padx=(7, 0))
        app._entries.append(self.entry)

        self.bar_l = Bar(self, app, lambda v: self._bar("l", v))
        self.bar_h = Bar(self, app, lambda v: self._bar("h", v))
        self.bar_s = Bar(self, app, lambda v: self._bar("s", v))
        self.bar_l.color_at = lambda f: "#%02x%02x%02x" % ((round(f * 255),) * 3)   # black -> white
        self.bar_h.color_at = lambda f: self._hex(f, 0.5, 1.0)                    # spectrum
        self.bar_l.pack(fill="x", pady=(14, 0))
        self.bar_h.pack(fill="x")
        self.bar_s.pack(fill="x")
        app._custom.append(self)
        self.set(variable.get())

    # color model
    @staticmethod
    def _hex(h, l, s):
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))

    def set_label(self, text):
        self.label.configure(text=text)

    def set(self, color, notify=False):
        """Set the color from a #rrggbb string (invalid values are ignored)."""
        rgb = self.app._rgb(color)
        if not rgb or not _HEX6.match(color):
            return False
        h, l, s = colorsys.rgb_to_hls(*[v / 255.0 for v in rgb])
        if s > 0 and 0 < l < 1:
            self.h = h                           # grays have no hue: keep the previous one
        self.l, self.s = l, s
        self._sync(notify)
        return True

    def _bar(self, kind, value):
        setattr(self, kind, value)
        if kind == "h" and self.s < 0.05 and 0.04 < self.l < 0.96:
            self.s = 0.6                         # a gray has no hue: give it some color
        self._sync(True)

    def _sync(self, notify):
        color = self._hex(self.h, self.l, self.s)
        self.var.set(color)
        if self.entry.get() != color:
            self.entry.delete(0, "end")
            self.entry.insert(0, color)
        self.swatch.set_inner_color(color)
        self.bar_l.set_value(self.l)
        self.bar_h.set_value(self.h)
        self.bar_s.set_value(self.s)
        self.bar_s.color_at = lambda f: self._hex(self.h, self.l, f)
        self.bar_s.recolor()
        if notify:
            self.on_change()

    def _typing(self, event):
        text = self.entry.get().strip()
        if len(text) == 7 and _HEX6.match(text) and text.lower() != self.var.get().lower():
            self.set(text, notify=True)

    def _commit(self):
        text = self.entry.get().strip()
        if text.lower() == self.var.get().lower():
            return                               # nothing changed (e.g. the field just lost focus)
        if not self.set(text, notify=True):
            self._sync(False)                    # invalid text: show the real color again

    def restyle(self):
        p = self.app.pal
        self.configure(bg=p["bg"])
        self.entry.configure(bg=p["bg"], fg=p["fg"], insertbackground=p["fg"],
                             selectbackground=p["sel_bg"], selectforeground=p["sel_fg"])


# -------------------------------------------------------------------- GUI
class App(tk.Tk):
    PANEL_W = 239            # width of the left column (all its elements are as wide as this)

    def __init__(self):
        super().__init__(className=APP_NAME)
        self.title(APP_NAME)
        self.iconname(APP_NAME)
        self.geometry("764x487")
        self.minsize(720, 487)
        self.pal = dict(DEFAULT_PALETTE)
        self.ui_font = tkfont.Font(family="Sans", size=10)
        self._ref_font = tkfont.Font(family="Sans", size=-PV_MENU_FONT_PX)   # sizes the preview menu
        self._frames, self._labels, self._entries, self._custom = [], [], [], []
        self._rgb_cache, self._edge_cache = {}, {}
        self._fam_cache, self._font_memo = None, {}
        self._font_cache, self._font_objs, self._img_cache = {}, {}, {}
        self._icon_paths_now = []
        self._menu_sig, self._menu_cache, self._icon_note = None, [], None
        self._icons_sig = ()
        self._hint_sig = "none"
        self._menu_override = _load_cache().get("menu_file")
        self.icon_sel = DEFAULT_ICON_SET
        self._draw_job, self._drawn_key, self._status_job = None, None, None
        self._status_wrap = 0
        self._theme_rev = 0
        self._busy = False
        self._styled = False
        self._wp_images, self._wp_photos, self._wp_pending = {}, {}, set()
        self.theme = None
        self.current = None
        self.section = "style"
        self.wp_mode = "tiled"
        self.wp_file = None

        try:
            locale.setlocale(locale.LC_TIME, "")        # clock format in the user's language
        except locale.Error:
            pass
        self._load_window_icon()
        ensure_setup()
        self._build_ui()
        self.restyle()           # colors of the app follow the applied theme
        self.bind("<FocusIn>", self._on_focus_in)
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
        f = tk.Frame(parent, bd=0, highlightthickness=0, **kw)
        self._frames.append(f)
        return f

    def _label(self, parent, **kw):
        lab = tk.Label(parent, anchor="w", font=self.ui_font, **kw)
        self._labels.append(lab)
        return lab

    # -- layout (see the mockups): tabs + status on top, left column, preview on the right.
    # Every element of the left column is exactly PANEL_W wide, so all edges line up.
    def _build_ui(self):
        main = self._frame(self)
        main.pack(fill="both", expand=True, padx=(17, 15), pady=(19, 14))
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(1, weight=1)

        nav = self._frame(main, width=self.PANEL_W, height=30)
        nav.grid_propagate(False)
        nav.grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.section_buttons = {}
        for i, (text, section) in enumerate((("Style", "style"), ("Background", "background"),
                                             ("Menu", "menu"))):
            b = ThemeButton(nav, self, text, lambda value=section: self.show_section(value))
            b.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0))
            nav.grid_columnconfigure(i, weight=1)
            nav.grid_rowconfigure(0, weight=1)
            self.section_buttons[section] = b

        # fixed-height box: a long status message never moves the rest of the layout
        status_box = self._frame(main, height=30)
        status_box.pack_propagate(False)
        status_box.grid(row=0, column=1, sticky="ew", padx=(16, 0), pady=(0, 12))
        self.status = tk.Label(status_box, text="", anchor="w", justify="left", font=("Sans", 9))
        self.status.pack(fill="both", expand=True)
        self.status.bind("<Configure>", self._on_status_resize)

        left = self._frame(main, width=self.PANEL_W)
        left.pack_propagate(False)
        left.grid(row=1, column=0, sticky="ns")
        self._build_style_panel(left)
        self._build_background_panel(left)
        self._build_menu_panel(left)
        self.style_panel.pack(fill="both", expand=True)

        right = self._frame(main)
        right.grid(row=1, column=1, sticky="nsew", padx=(16, 0))
        self.canvas = tk.Canvas(right, highlightthickness=1, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.schedule_draw())

    def _build_style_panel(self, left):
        panel = self.style_panel = self._frame(left)
        btns = self._frame(panel)
        btns.pack(side="bottom", fill="x", pady=(14, 0))
        for i, (text, cmd) in enumerate((("Apply", self.apply), ("Reset default", self.reset),
                                         ("Reload list", self.refresh))):
            ThemeButton(btns, self, text, cmd).pack(fill="x", pady=(0 if i == 0 else 5, 0))

        # icon sets: fixed height, right above the buttons
        ibox = Bevel(panel, self, height=96)
        ibox.pack(side="bottom", fill="x")
        self._label(panel, text="Icons").pack(side="bottom", fill="x", pady=(12, 4))
        self.icons_list = tk.Listbox(ibox.inner, relief="flat", bd=0, highlightthickness=0,
                                     activestyle="none", font=self.ui_font, exportselection=False)
        self.icons_list.pack(fill="both", expand=True)
        for seq in ("<<ListboxSelect>>", "<ButtonRelease-1>", "<KeyRelease-Up>",
                    "<KeyRelease-Down>", "<KeyRelease-Prior>", "<KeyRelease-Next>",
                    "<KeyRelease-Home>", "<KeyRelease-End>"):
            self.icons_list.bind(seq, lambda e: self._icon_selected())

        # themes: take the remaining height
        self._label(panel, text="Themes").pack(fill="x", pady=(0, 4))
        box = Bevel(panel, self)
        box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(box.inner, relief="flat", bd=0, highlightthickness=0,
                                  activestyle="none", font=self.ui_font, exportselection=False)
        self.listbox.pack(fill="both", expand=True)
        # No polling: every way of changing the selection is bound instead.
        for seq in ("<<ListboxSelect>>", "<ButtonRelease-1>", "<KeyRelease-Up>",
                    "<KeyRelease-Down>", "<KeyRelease-Prior>", "<KeyRelease-Next>",
                    "<KeyRelease-Home>", "<KeyRelease-End>"):
            self.listbox.bind(seq, lambda e: self._select_changed())
        self.listbox.bind("<Double-Button-1>", lambda e: self.apply())

    def _build_menu_panel(self, left):
        panel = self.menu_panel = self._frame(left)
        self.menu_path = tk.StringVar(value="")
        row = self._frame(panel)
        row.pack(fill="x")
        title = self._label(row, text="Menu file:", cursor="hand2")
        title.pack(side="left")
        title.bind("<Button-1>", lambda e: self._browse_menu_file())      # click: browse
        field = Bevel(panel, self, height=28)
        field.pack(fill="x", pady=(6, 0))
        self.menu_entry = tk.Entry(field.inner, textvariable=self.menu_path, relief="flat", bd=0,
                                   highlightthickness=0, font=self.ui_font)
        self.menu_entry.pack(fill="both", expand=True, padx=6)
        self.menu_entry.bind("<Return>", lambda e: self._set_menu_file(self.menu_path.get()))
        self._entries.append(self.menu_entry)
        self.menu_info = self._label(panel, text="", justify="left", wraplength=self.PANEL_W)
        self.menu_info.pack(fill="x", pady=(12, 0))

    def _refresh_menu_panel(self):
        path = self._menu_file()
        entries = self._menu_entries_now()
        self.menu_path.set(path or "")
        self.menu_entry.xview_moveto(0)
        tools = svg_tools()
        svg = ("svg icons are drawn with: %s" % tools[0]) if tools else \
            "svg icons: no renderer installed (sudo apt install librsvg2-bin)"
        if path:
            self.menu_info.configure(text="%d entries in the preview menu.\n\nEdit the file and come "
                                          "back here: the preview follows.\n\n%s" % (len(entries), svg))
        else:
            self.menu_info.configure(text="Not found.\n\nType the path of your menu file and press "
                                          "Enter, or click \"Menu file:\" to browse. It is searched "
                                          "in ~/.jwm/jwm_menu, ~/.jwm_menu and in the files your "
                                          "~/.jwmrc includes.")

    def _browse_menu_file(self):
        start = os.path.dirname(self._menu_file() or "") or (JWM_DIR if os.path.isdir(JWM_DIR)
                                                              else HOME)
        chosen = filedialog.askopenfilename(parent=self, initialdir=start, title="Menu file")
        if chosen:
            self._set_menu_file(chosen)

    def _set_menu_file(self, path):
        """Choose the file the preview menu is read from (empty = find it automatically)."""
        path = os.path.expanduser((path or "").strip())
        if path and not os.path.isfile(path):
            self.set_status("File not found: %s" % path)
            self._refresh_menu_panel()
            return
        self._menu_override = path or None
        cache = _load_cache()
        if path:
            cache["menu_file"] = path
        else:
            cache.pop("menu_file", None)
        _save_cache(cache)
        self._menu_sig = None
        self._hint_sig = "none"
        self._refresh_menu_panel()
        self.draw(force=True)

    def _build_background_panel(self, left):
        panel = self.background_panel = self._frame(left)
        bottom = self._frame(panel)
        bottom.pack(side="bottom", fill="x", pady=(14, 0))
        ThemeButton(bottom, self, "Apply to Theme", self.save_background).pack(fill="x")
        ThemeButton(bottom, self, "Use JWM Default Background", self.reset_background).pack(
            fill="x", pady=(5, 0))

        self.bg_mode = tk.StringVar(value="solid")
        self.bg_default = tk.BooleanVar(value=False)
        self.bg_color1 = tk.StringVar(value="#2b2b2b")
        self.bg_color2 = tk.StringVar(value="#387cb0")
        self.wp_dir = tk.StringVar(value="")
        radios = self._frame(panel)
        radios.pack(fill="x", pady=(10, 0))
        for text, value in (("Solid color", "solid"), ("Gradient", "gradient"),
                            ("Image", "image")):
            ThemeRadio(radios, self, text, self.bg_mode, value,
                       self._background_changed).pack(fill="x")

        body = self.bg_body = self._frame(panel)
        body.pack(fill="both", expand=True, pady=(22, 0))

        # solid color / gradient: one or two color pickers
        self.colors_frame = self._frame(body)
        self.picker1 = ColorPicker(self.colors_frame, self, "Color", self.bg_color1,
                                   self._color_changed)
        self.picker1.pack(fill="x")
        self.picker2 = ColorPicker(self.colors_frame, self, "Color 2", self.bg_color2,
                                   self._color_changed)

        # image: directory, style button and the list of image files
        img = self.image_frame = self._frame(body)
        row = self._frame(img)
        row.pack(fill="x")
        box = self._frame(row, width=51, height=28)
        box.pack_propagate(False)
        box.pack(side="left")
        path_label = self._label(box, text="Path:", cursor="hand2")
        path_label.pack(fill="both", expand=True)
        path_label.bind("<Button-1>", lambda e: self._browse_dir())   # click: choose a folder
        field = Bevel(row, self, height=28)
        field.pack_propagate(False)
        field.pack(side="left", fill="x", expand=True)
        self.path_entry = tk.Entry(field.inner, textvariable=self.wp_dir, relief="flat", bd=0,
                                   highlightthickness=0, font=self.ui_font)
        self.path_entry.pack(fill="both", expand=True, padx=6)
        self.path_entry.bind("<Return>", lambda e: self._load_wallpaper_dir(self.wp_dir.get()))
        self._entries.append(self.path_entry)
        self.wp_mode_btn = ThemeButton(img, self, "Set Tiled", self._cycle_wp_mode)
        self.wp_mode_btn.pack(fill="x", pady=(14, 0))
        fbox = Bevel(img, self)
        fbox.pack(fill="both", expand=True, pady=(14, 0))
        self.files_list = tk.Listbox(fbox.inner, relief="flat", bd=0, highlightthickness=0,
                                     activestyle="none", font=self.ui_font, exportselection=False)
        self.files_list.pack(fill="both", expand=True)
        self.files_list.bind("<<ListboxSelect>>", lambda e: self._wp_selected())
        self.files_list.bind("<ButtonRelease-1>", lambda e: self._wp_selected())
        self._show_bg_mode()

    # -- status line: auto-clears, so the idle window looks like the mockup
    def _on_status_resize(self, event):
        wrap = max(100, event.width - 4)
        if abs(wrap - self._status_wrap) > 2:       # the box has a fixed height: no layout loop
            self._status_wrap = wrap
            self.status.configure(wraplength=wrap)

    def set_status(self, msg, clear_after=9000):
        self.status.config(text=msg)
        if self._status_job:
            self.after_cancel(self._status_job)
            self._status_job = None
        if msg and clear_after:
            self._status_job = self.after(clear_after, lambda: self.status.config(text=""))

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
        self.set_status("ERROR: %s: %s" % (exc.__name__, val), clear_after=0)

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
        """Build the app palette from a parsed theme (the one currently applied).

        - window / list background  <- menu background (MenuStyle)
        - selected-theme bar        <- selected menu item (MenuStyle/Active)
        - buttons                   <- panel colors and look (TrayStyle): motif themes give
                                       raised bevels, flat themes flat buttons; pressed buttons
                                       use the panel's Active colors
        - selected section tab      <- the panel's active window button (TaskListStyle/Active)
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
        for lst in (self.listbox, self.icons_list, self.files_list):
            lst.configure(bg=p["bg"], fg=p["fg"], selectbackground=p["sel_bg"],
                          selectforeground=p["sel_fg"])
        for ent in self._entries:
            ent.configure(bg=p["bg"], fg=p["fg"], insertbackground=p["fg"],
                          selectbackground=p["sel_bg"], selectforeground=p["sel_fg"])
        self.canvas.configure(bg=p["bg"], highlightbackground=p["edge"],
                              highlightcolor=p["edge"])
        for widget in self._custom:      # buttons, radios, bevels, sliders
            widget.restyle()
        self._update_tabs()

    def _update_tabs(self):
        for section, button in self.section_buttons.items():
            button.set_selected(section == self.section)

    # -- actions
    def refresh(self):
        _PARSE_CACHE.clear()             # "Reload list" re-reads the theme files
        _ICON_MEMO.clear()
        _LOGO_MEMO.clear()
        self._img_cache.clear()
        self.listbox.delete(0, "end")
        self.current = None
        for n in list_themes():
            self.listbox.insert("end", n)
        self._fill_icon_list()
        if self.listbox.size():
            self.listbox.selection_set(0)
            self.on_select()
        else:
            self._set_theme(None)
            self.draw()
            self.set_status("No theme found in %s (needs <theme>/.jwmrc)" % THEMES_DIR)

    # -- icon sets (folders of ~/.jwm/icons)
    def _fill_icon_list(self):
        self.icons_list.delete(0, "end")
        for name in list_icon_sets():
            self.icons_list.insert("end", name)
        self._select_icon_set(self.icon_sel)

    def _select_icon_set(self, name):
        names = list(self.icons_list.get(0, "end"))
        if name not in names:
            name = DEFAULT_ICON_SET
        self.icon_sel = name
        self.icons_list.selection_clear(0, "end")
        if name in names:
            self.icons_list.selection_set(names.index(name))
            self.icons_list.see(names.index(name))

    def _icon_selected(self):
        sel = self.icons_list.curselection()
        if sel and self.icons_list.get(sel[0]) != self.icon_sel:
            self.icon_sel = self.icons_list.get(sel[0])
            self.draw()                                         # the preview shows the new icons

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
        self._select_icon_set(self.theme["icon_set"])          # the list shows the theme's icons
        if self.theme["error"]:
            self.set_status("Error in file: " + self.theme["error"], clear_after=0)
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
        self.set_status("Applied %s - restarting JWM ..." % name, clear_after=0)
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
        wanted = self.icon_sel
        if self.theme and not self.theme.get("error") and wanted != self.theme["icon_set"]:
            # a different icon set than the one in the theme file: write it into the theme
            if not self._edit_theme_file(lambda data: rewrite_icons(data, wanted)):
                return
            self._select_icon_set(wanted)
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
        self._update_tabs()
        for panel in (self.style_panel, self.background_panel, self.menu_panel):
            panel.pack_forget()
        panel = {"style": self.style_panel, "background": self.background_panel,
                 "menu": self.menu_panel}[section]
        panel.pack(fill="both", expand=True)
        if section == "background":
            self.load_background_controls()
        elif section == "menu":
            self._refresh_menu_panel()
        self.draw()

    # -- Background section ------------------------------------------------------------
    def _to_hex(self, color, default):
        rgb = self._rgb(color) if color else None
        return "#%02x%02x%02x" % rgb if rgb else default

    def load_background_controls(self):
        """Fill the Background controls from the selected theme."""
        t = self.theme
        if not t or t.get("error"):
            return
        wp = t.get("wallpaper")
        colors = split_grad(t["colors"].get("desktop", "#2b2b2b"))
        defined = t.get("desktop_defined", False)
        self.picker1.set(self._to_hex(colors[0] if colors and defined else "", "#000000"))
        self.picker2.set(self._to_hex(colors[1] if len(colors) > 1 else "", "#387cb0"))
        if wp:
            self.bg_mode.set("image")
            self.wp_mode = wp[0] if wp[0] in dict(WALLPAPER_MODES) else "tiled"
            self.wp_file = wp[1]
            self._load_wallpaper_dir(os.path.dirname(wp[1]), select=wp[1])
        else:
            self.bg_mode.set("gradient" if len(colors) > 1 and defined else "solid")
        self.bg_default.set(not defined and not wp)
        self._update_mode_button()
        self._show_bg_mode()

    def _show_bg_mode(self):
        mode = self.bg_mode.get()
        self.colors_frame.pack_forget()
        self.image_frame.pack_forget()
        if mode == "image":
            self.image_frame.pack(fill="both", expand=True)
            return
        self.colors_frame.pack(fill="x")
        self.picker1.set_label("Color" if mode == "solid" else "Color 1")
        if mode == "gradient":
            self.picker2.pack(fill="x", pady=(30, 0))     # second color only for gradients
        else:
            self.picker2.pack_forget()

    def _background_changed(self):
        self.bg_default.set(False)
        self._show_bg_mode()
        if self.section == "background":
            self.draw()

    def _color_changed(self):
        self.bg_default.set(False)
        self.schedule_draw()

    def _update_mode_button(self):
        self.wp_mode_btn.set_text(dict(WALLPAPER_MODES)[self.wp_mode])

    def _cycle_wp_mode(self):
        keys = [m for m, _ in WALLPAPER_MODES]
        self.wp_mode = keys[(keys.index(self.wp_mode) + 1) % len(keys)]
        self._update_mode_button()
        self.bg_default.set(False)
        self.draw()

    def _browse_dir(self):
        start = os.path.expanduser(self.wp_dir.get()) or HOME
        chosen = filedialog.askdirectory(parent=self, initialdir=start if os.path.isdir(start)
                                         else HOME, title="Folder with the wallpapers")
        if chosen:
            self._load_wallpaper_dir(chosen)

    def _load_wallpaper_dir(self, path, select=None):
        """List the image files (png, jpg) of a folder."""
        path = os.path.expanduser((path or "").strip())
        self.wp_dir.set(path)
        self.path_entry.xview_moveto(0)
        self.files_list.delete(0, "end")
        if not os.path.isdir(path):
            if path:
                self.set_status("Folder not found: %s" % path)
            return
        try:
            names = sorted((n for n in os.listdir(path)
                            if n.lower().endswith(IMAGE_EXT)
                            and os.path.isfile(os.path.join(path, n))), key=str.lower)
        except OSError as exc:
            self.set_status("Cannot read the folder: %s" % exc)
            return
        for i, n in enumerate(names):
            self.files_list.insert("end", n)
            if select and os.path.join(path, n) == select:
                self.files_list.selection_set(i)
                self.files_list.see(i)

    def _wp_selected(self):
        sel = self.files_list.curselection()
        if not sel:
            return
        file = os.path.join(self.wp_dir.get(), self.files_list.get(sel[0]))
        if file != self.wp_file:
            self.wp_file = file
            self.bg_default.set(False)
            self.draw()

    def _edit_theme_file(self, transform):
        """Rewrite the selected theme file with transform(text). True on success."""
        name = self.selected() or self.current
        path = theme_path(name or "")
        if not name or not os.path.isfile(path):
            self.set_status("Select a valid theme first")
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
            new = transform(data)
            shutil.copy2(path, path + ".bak")
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
        except Exception as exc:
            self.set_status("Background update error: %s" % exc)
            return False
        _PARSE_CACHE.pop(path, None)
        self.current = name
        self._set_theme(parse_theme_cached(path))
        return True

    def save_background(self):
        """Write the chosen background into the selected theme, apply it, restart JWM."""
        if self._busy:
            return
        if not self.current:
            self.set_status("Select a theme first")
            return
        mode = self.bg_mode.get()
        if mode == "image":
            file = self.wp_file
            if not file or not os.path.isfile(file):
                self.set_status("Choose an image in the list first")
                return
            if not os.path.isfile(WALLPAPER_SCRIPT):
                self.set_status("Wallpaper script not found: copy jwmanager-wallpaper.sh "
                                "to %s" % JWM_DIR, clear_after=0)
                return
            mode_name = self.wp_mode

            def transform(data):
                return rewrite_wallpaper(rewrite_background(data, "image"), mode_name, file)
        else:
            c1, c2 = self.bg_color1.get(), self.bg_color2.get()

            def transform(data):
                return rewrite_wallpaper(rewrite_background(data, mode, c1, c2))
        if self._edit_theme_file(transform):
            self.load_background_controls()
            self.apply_file(self.current)

    def reset_background(self):
        """Back to the background the theme originally had (and no wallpaper script)."""
        if self._busy:
            return
        if not self.current:
            self.set_status("Select a theme first")
            return
        if self._edit_theme_file(
                lambda data: rewrite_wallpaper(rewrite_background(data, "default"))):
            self.load_background_controls()
            self.apply_file(self.current)

    # -- preview ------------------------------------------------------------------------
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

    def _bevel(self, x1, y1, x2, y2, base, raised=True, width=1, canvas=None):
        """Raised or sunken bevel, Motif / Windows 98 style."""
        c = canvas or self.canvas
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

    def _icon_font(self, tray_font):
        """Find an installed Nerd Font (preferring the tray one)."""
        if tray_font not in self._font_memo:
            self._font_memo[tray_font] = self._find_icon_font(self._families(), tray_font)
        return self._font_memo[tray_font]

    @staticmethod
    def _find_icon_font(fams, tray_font):
        norm = lambda x: re.sub(r"[^a-z0-9]", "", x.lower())
        want = norm(font_family(tray_font))
        if want and "nerd" in want:                  # the panel font is itself a Nerd Font
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

    # -- wallpaper preview: the image is prepared in a thread, the window never waits for it
    def _wallpaper_photo(self, path, mode, w, h):
        """PhotoImage of the wallpaper as feh would paint it, or None (not ready / no Pillow)."""
        if not path or not os.path.isfile(path):
            return None
        pil = pil_modules()
        if pil["Image"] is None:
            if not self.__dict__.get("_pil_note"):
                self._pil_note = True
                self.set_status("Install python3-pil to preview wallpapers", clear_after=0)
            return None
        key = (path, mode, w, h)
        photo = self._wp_photos.get(key)
        if photo is not None:
            return photo
        if key in self._wp_images:
            image = self._wp_images[key]
            if image is None:
                return None              # unreadable image
            photo = self._to_photo(image)
            self._wp_photos[key] = photo
            while len(self._wp_photos) > 4:           # keep a few pictures only
                self._wp_photos.pop(next(iter(self._wp_photos)))
                self._wp_images.pop(next(iter(self._wp_images)), None)
            return photo
        if key not in self._wp_pending:
            self._wp_pending.add(key)
            screen = (self.winfo_screenwidth(), self.winfo_screenheight())
            threading.Thread(target=self._wp_render, args=(key, screen), daemon=True).start()
            self.after(80, self._wp_check)
        return None

    def _wp_render(self, key, screen):
        path, mode, w, h = key
        try:
            self._wp_images[key] = render_wallpaper(path, mode, w, h, screen[0], screen[1])
        except Exception:
            self._wp_images[key] = None
        finally:
            self._wp_pending.discard(key)

    def _wp_check(self):
        if self._wp_pending:
            self.after(80, self._wp_check)
        else:
            self.draw(force=True)

    def _to_photo(self, image):
        tk_module = pil_modules()["ImageTk"]
        if tk_module is not None:
            try:
                return tk_module.PhotoImage(image, master=self)
            except Exception:
                pass                                  # broken ImageTk: use the PNG route
        buf = io.BytesIO()                            # no ImageTk: Tk reads PNG data itself
        image.save(buf, "PNG")
        return tk.PhotoImage(data=base64.b64encode(buf.getvalue()), master=self)

    def _bg_state(self):
        return (self.bg_default.get(), self.bg_mode.get(), self.bg_color1.get(),
                self.bg_color2.get(), self.wp_file, self.wp_mode)

    def draw_background_preview(self, w, h):
        c = self.canvas
        mode = self.bg_mode.get()
        if mode == "image" and not self.bg_default.get():
            photo = self._wallpaper_photo(self.wp_file, self.wp_mode, w, h)
            if photo:
                c.create_image(0, 0, anchor="nw", image=photo)
            else:
                self._fill(0, 0, w, h, ("#1e1e1e", None))
        else:
            if self.bg_default.get():
                spec = ("#000000", None)  # JWM's unconfigured desktop background preview
            elif mode == "gradient":
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
        self._draw_tray(w, h, raw, S, C, col)

    # -- fonts: every element of the preview uses the font its style has in the theme
    def _family(self, fam):
        return fam if fam in ("Sans", "Serif", "Monospace") or fam in self._families() else "Sans"

    def _font_tuple(self, spec):
        """Tk font (family, -pixels[, style]) for a JWM font name such as 'Sans-12:bold'."""
        key = spec or ""
        f = self._font_cache.get(key)
        if f is None:
            fam, px, bold, italic = parse_font(spec)
            style = " ".join(x for x, on in (("bold", bold), ("italic", italic)) if on)
            f = (self._family(fam), -px, style) if style else (self._family(fam), -px)
            self._font_cache[key] = f
        return f

    def _font_obj(self, spec):
        key = spec or ""
        f = self._font_objs.get(key)
        if f is None:
            fam, px, bold, italic = parse_font(spec)
            f = tkfont.Font(family=self._family(fam), size=-px,
                            weight="bold" if bold else "normal",
                            slant="italic" if italic else "roman")
            self._font_objs[key] = f
        return f

    def _fit_text(self, spec, text, max_px):
        """Text shortened with '...' so that it fits in max_px pixels."""
        f = self._font_obj(spec)
        if f.measure(text) <= max_px:
            return text
        while text and f.measure(text + "\u2026") > max_px:
            text = text[:-1]
        return text + "\u2026" if text else ""

    # -- images: icons, logo, application icon (scaled to a box, small ones are enlarged)
    def _photo(self, path, max_w, max_h):
        """PhotoImage of an image file scaled to fit in max_w x max_h (small images are enlarged,
        like JWM does), or None if it cannot be read. The picture is always built from the
        original file: nothing is redrawn."""
        if not path:
            return None
        try:
            stamp = os.stat(path).st_mtime_ns          # a replaced icon file is picked up
        except OSError:
            return None
        key = (path, stamp, max_w, max_h)
        if key in self._img_cache:
            return self._img_cache[key]
        img = None
        try:
            img = self._photo_pillow(path, max_w, max_h)
        except Exception:
            img = None
        if img is None and not path.lower().endswith(".svg"):
            img = self._photo_tk(path, max_w, max_h)   # Tk loads the original file itself
        self._img_cache[key] = img
        return img

    def _photo_pillow(self, path, max_w, max_h):
        Image = pil_modules()["Image"]
        if path.lower().endswith(".svg"):                  # rasterized by an external tool
            data = svg_to_png(path, 2 * max(max_w, max_h))
            if data is None:
                return None
            if Image is None:
                return tk.PhotoImage(data=base64.b64encode(data), master=self)
            source = io.BytesIO(data)
        else:
            if Image is None:
                return None
            source = path
        src = Image.open(source).convert("RGBA")
        scale = min(max_w / float(src.width), max_h / float(src.height))
        size = (max(1, round(src.width * scale)), max(1, round(src.height * scale)))
        try:
            resample = Image.Resampling.LANCZOS if scale < 1 else Image.Resampling.BICUBIC
        except AttributeError:
            resample = Image.LANCZOS if scale < 1 else Image.BICUBIC
        out = src.resize(size, resample)
        before, after = opaque_brightness(src), opaque_brightness(out)
        if before and before > 40 and (after is None or after < 0.35 * before):
            raise ValueError("scaling darkened the icon")  # never show a corrupted copy
        if not path.lower().endswith(".svg"):
            native = self._tk_brightness(path)             # what Tk itself reads from the file
            if native and native > 40 and (after is None or after < 0.35 * native):
                raise ValueError("Pillow reads this file darker than Tk does")
        return self._to_photo(out)

    def _tk_brightness(self, path):
        """Mean brightness of the visible pixels of a file as Tk reads it (None if Tk cannot)."""
        try:
            raw = tk.PhotoImage(file=path, master=self)
            w, h = raw.width(), raw.height()
            total = count = 0
            for iy in range(12):
                for ix in range(12):
                    x, y = min(w - 1, ix * w // 12), min(h - 1, iy * h // 12)
                    if raw.transparency_get(x, y):
                        continue
                    r, g, b = raw.get(x, y)[:3]
                    total += (int(r) + int(g) + int(b)) / 3.0
                    count += 1
            return total / count if count >= 6 else None
        except Exception:
            return None

    def _photo_tk(self, path, max_w, max_h):
        """The original file loaded by Tk (png / gif / ppm), scaled by whole factors only."""
        try:
            raw = tk.PhotoImage(file=path, master=self)
            scale = min(max_w / float(raw.width()), max_h / float(raw.height()))
            if scale >= 1:
                return raw.zoom(max(1, int(scale)))
            return raw.subsample(max(1, int(round(1.0 / scale))))
        except Exception:
            return None

    def _logo_image(self, icon_paths, max_w, max_h):
        """The JWM logo of the panel menu button (None if not found)."""
        return self._photo(find_logo(icon_paths), max_w, max_h)

    def _icon_photo(self, name, size):
        """Image of icon="name" looked up in the icon paths of the previewed set."""
        return self._photo(find_icon(name, self._icon_paths_now), size, size)

    def _effective_icon_paths(self, raw):
        """<IconPath> list the preview uses: the theme's own, or the icon set selected in the
        list (which replaces them, exactly as applying it would)."""
        chosen, current = self.icon_sel, raw["icon_set"]
        if chosen and chosen != current:
            if chosen == DEFAULT_ICON_SET:
                own = raw["icon_default_paths"]
                return own if own is not None else raw["icon_paths"]
            return [icon_set_path(chosen)]
        return raw["icon_paths"]

    @staticmethod
    def _clock_text(fmt):
        try:
            return time.strftime(fmt or "%H:%M")
        except ValueError:
            return "12:34"

    def draw(self, force=False):
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 300 or h < 200:
            return
        # Nothing to do if what the picture depends on has not changed.
        raw = self.theme
        paths = self._effective_icon_paths(raw) if raw else []
        isig = self._icons_signature(paths)
        key = (self._theme_rev, w, h, self.section, self.icon_sel, self._menu_signature(), isig,
               self._bg_state() if self.section == "background" else None)
        if key == self._drawn_key and not force:
            return
        self._drawn_key = key
        if isig != self._icons_sig:                 # icons were added / removed: look again
            self._icons_sig = isig
            _ICON_MEMO.clear()
            self._img_cache.clear()
        c.delete("all")
        if not raw:
            return
        self._icon_paths_now = paths
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
        F = lambda size=9: (fam, size)              # sample text inside the windows
        FT = lambda key: self._font_tuple(raw["fonts"].get(key))   # fonts of the theme

        tray_h = raw["tray_h"]
        top_tray = raw["tray_pos"] == "top"
        ay1 = tray_h if top_tray else 0            # usable area (without tray)
        ay2 = h if top_tray else h - tray_h
        H = ay2 - ay1

        wp = raw.get("wallpaper")                               # desktop background
        photo = self._wallpaper_photo(wp[1], wp[0], w, h) if wp else None
        if photo:
            c.create_image(0, 0, anchor="nw", image=photo)
        else:
            self._fill(0, 0, w, h, S("desktop"), vertical=True)

        bw = raw["border"]
        th = raw["title_h"]
        title_spec = raw["fonts"].get("window")

        def glyphs(cx, cy, r, kind, color, thick):
            """Window button symbols: close (X), maximize (square), minimize (dash)."""
            if kind == "close":
                c.create_line(cx - r, cy - r, cx + r + 1, cy + r + 1, fill=color, width=thick)
                c.create_line(cx - r, cy + r, cx + r + 1, cy - r - 1, fill=color, width=thick)
            elif kind == "max":
                c.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline=color, width=thick)
            else:
                c.create_line(cx - r, cy + r - 1, cx + r + 1, cy + r - 1, fill=color, width=2)

        def motif_window(x, y, ww, hh, pre, label):
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
            shown = self._fit_text(title_spec, label, tx2 - 3 * th - tx1 - 14)
            c.create_text(tx1 + 8, cy, text=shown, anchor="w", fill=txt, font=FT("window"))
            r = max(4, int(th * 0.22))
            for i, kind in enumerate(("close", "max", "min")):           # right to left
                bx2 = tx2 - i * th
                bx1 = bx2 - th
                self._bevel(bx1, ty1, bx2, ty2, base, True, 1)           # raised button
                glyphs((bx1 + bx2) / 2, cy, r, kind, txt, 2)
            c.create_text(tx1 + 10, ty2 + 18, text="Window content", anchor="w",
                          fill="#9a9a9a", font=F(9))

        def flat_window(x, y, ww, hh, pre, label):
            """Flat frame: Outline color border, symbols without boxes."""
            txt, outline = C(pre + "_text"), C(pre + "_outline")
            c.create_rectangle(x, y, x + ww, y + hh, fill=C(pre + "_title"), outline="")  # frame
            self._fill(x + bw, y + bw, x + ww - bw, y + bw + th, S(pre + "_title"))
            c.create_rectangle(x + bw, y + bw + th, x + ww - bw, y + hh - bw,
                               fill="#1e1e1e", outline="")
            if bw > 1:                       # thick frame: a thin line also runs round the client
                c.create_rectangle(x + bw - 1, y + bw + th - 1, x + ww - bw, y + hh - bw,
                                   outline=outline)
            c.create_rectangle(x, y, x + ww - 1, y + hh - 1, outline=outline)             # outline
            cy = y + bw + th / 2
            shown = self._fit_text(title_spec, label, ww - 3 * 20 - 2 * bw - 20)
            c.create_text(x + bw + 8, cy, text=shown, anchor="w", fill=txt, font=FT("window"))
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
                motif_window(x, y, ww, hh, pre, label)
            else:
                flat_window(x, y, ww, hh, pre, label)

        window(w * 0.05, ay1 + H * 0.10, w * 0.46, H * 0.40, False, "Inactive window")
        window(w * 0.20, ay1 + H * 0.34, w * 0.50, H * 0.46, True, "Active window")

        self._draw_menu(raw, S, C, w, ay1, H)
        self._draw_tray(w, h, raw, S, C, col)

    # -- the preview menu: always the entries of the jwm_menu file, whatever the theme is
    def _menu_file(self):
        """Menu file of the preview: the one chosen in the Menu tab, else a well-known place,
        else a file the applied ~/.jwmrc includes in its RootMenu."""
        if self._menu_override and os.path.isfile(self._menu_override):
            return self._menu_override
        for path in MENU_FILES:
            if os.path.isfile(path):
                return path
        applied = parse_theme_cached(TARGET) if os.path.isfile(TARGET) else None
        for path in (applied or {}).get("menu_includes", []):
            if os.path.isfile(path):
                return path
        return None

    def _menu_signature(self):
        """(path, modification time, size) of the menu file: changes when the file changes."""
        path = self._menu_file()
        try:
            st = os.stat(path)
            return (path, st.st_mtime_ns, st.st_size)
        except (OSError, TypeError):
            return (None, 0, 0)

    def _menu_entries_now(self):
        """Top-level entries of ~/.jwm/jwm_menu (read again only when the file changes)."""
        sig = self._menu_signature()
        if sig != self._menu_sig:
            self._menu_sig = sig
            entries = []
            if sig[0]:
                try:
                    root = read_xml_fragment(sig[0])
                    if root.tag not in ("JWM", "RootMenu"):
                        holder = ET.Element("holder")
                        holder.append(root)
                        root = holder
                    entries = _menu_entries(root)
                except Exception:
                    entries = []
            self._menu_cache = entries[:MENU_LIMIT]
        return self._menu_cache

    def _icons_signature(self, paths):
        """Modification times of the icon folders: changes when icons are added or removed."""
        sig = []
        for d in paths:
            try:
                sig.append(os.stat(os.path.expanduser(d)).st_mtime_ns)
            except OSError:
                sig.append(0)
        return tuple(sig)

    def _on_focus_in(self, event):
        """Back from the editor or the file manager: if the menu file or the icons changed,
        the preview follows."""
        icons = self._icons_signature(self._effective_icon_paths(self.theme)) if self.theme else ()
        if self._menu_signature() != self._menu_sig or icons != self._icons_sig:
            self.schedule_draw()

    def _draw_menu(self, raw, S, C, w, ay1, H):
        """The menu of the jwm_menu file in the colors of the theme. Its size is fixed (a
        scaled-down JWM menu): only its colors and the icon set change from theme to theme."""
        c = self.canvas
        entries = self._menu_entries_now()
        if not entries:
            self._menu_hint()
            return
        family = self._family(parse_font(raw["fonts"].get("menu"))[0])
        font = (family, -PV_MENU_FONT_PX)
        has_icons = any(e["icon"] for e in entries)
        icon, item_h, sep_h = PV_MENU_ICON, PV_MENU_ITEM_H, PV_MENU_SEP_H
        height = lambda es: 2 + sum(sep_h if e["type"] == "separator" else item_h for e in es)
        while len(entries) > 1 and height(entries) > H - 24:     # too many entries: cut the tail
            entries = entries[:-1]
        text_x = 1 + 3 + (icon + 3 if has_icons else 3)
        longest = max([self._ref_font.measure(e["label"]) for e in entries if e["label"]] or [40])
        arrows = any(e["type"] == "menu" for e in entries)
        mw = text_x + longest + (12 + 4 + 3 if arrows else 8) + 1
        mh = height(entries)
        mx, my = int(w - mw - 12), int(ay1 + 12)
        motif = raw["menu_deco"] == "motif"
        if motif:
            self._fill(mx, my, mx + mw, my + mh, S("menu_bg"))
            self._bevel(mx, my, mx + mw, my + mh, C("menu_bg"), True, 1)
        else:
            c.create_rectangle(mx, my, mx + mw, my + mh, fill=C("menu_outline"), outline="")
            self._fill(mx + 1, my + 1, mx + mw - 1, my + mh - 1, S("menu_bg"))
        y = my + 1
        marked = next((i for i, e in enumerate(entries) if e["type"] != "separator"
                       and i >= 1), 0)                          # one entry shows the "selected" look
        declared, drawn = [], 0
        for i, e in enumerate(entries):
            if e["type"] == "separator":
                if motif:
                    light, dark = self._edges(C("menu_bg"))
                    c.create_line(mx + 3, y + 2, mx + mw - 4, y + 2, fill=dark)
                    c.create_line(mx + 3, y + 3, mx + mw - 4, y + 3, fill=light)
                else:
                    c.create_line(mx + 3, y + 3, mx + mw - 4, y + 3, fill=C("menu_outline"))
                y += sep_h
                continue
            if i == marked:
                self._fill(mx + 1, y, mx + mw - 1, y + item_h, S("menu_sel_bg"))
                fg = C("menu_sel_fg")
            else:
                fg = C("menu_fg")
            cy = y + item_h / 2
            if e["icon"]:
                declared.append(e["icon"])
                photo = self._icon_photo(e["icon"], icon)
                if photo:
                    drawn += 1
                    c.create_image(mx + 4, y + (item_h - icon) // 2, anchor="nw", image=photo)
            c.create_text(mx + text_x, cy, text=e["label"], anchor="w", fill=fg, font=font)
            if e["type"] == "menu":
                ax = mx + mw - 3 - 4 - 1
                c.create_polygon(ax, cy - 3, ax, cy + 4, ax + 4, cy, fill=fg, outline="")
            y += item_h
        self._icon_report(declared, drawn)

    def _menu_hint(self):
        """The preview has no menu: say why (once per file state)."""
        if self._menu_sig == self._hint_sig:
            return
        self._hint_sig = self._menu_sig
        if self._menu_sig and self._menu_sig[0]:
            self.set_status("The menu file has no readable entries: %s" % self._menu_sig[0],
                            clear_after=12000)
        else:
            self.set_status("Menu file not found: choose it in the Menu tab", clear_after=12000)

    def _icon_report(self, declared, drawn):
        """Tell why the menu has no icons (once per icon set / menu file), instead of failing
        silently."""
        key = (tuple(self._icon_paths_now), self._menu_sig)
        if drawn and SVG_NOTE["black"] and key != self._icon_note:
            self._icon_note = key                 # drawn, but the only svg renderer paints black
            self.set_status("svg icons look black: ImageMagick cannot draw them well. Install "
                            "rsvg-convert (sudo apt install librsvg2-bin)", clear_after=15000)
            return
        if not declared or drawn:
            if not SVG_NOTE["black"]:
                self._icon_note = None
            return
        if key == self._icon_note:
            return
        self._icon_note = key
        located = [find_icon(n, self._icon_paths_now) for n in declared]
        located = [x for x in located if x]
        if not located:
            where = self._icon_paths_now[0] if self._icon_paths_now else ""
            hint = ""
            if where and os.path.isdir(where):
                inner = glob.glob(os.path.join(where, "*", declared[0] + ".*"))
                if inner:
                    hint = " (it is in the subfolder '%s': JWM needs the icons directly in the " \
                           "set folder)" % os.path.basename(os.path.dirname(inner[0]))
            self.set_status("Menu icons not found: looked for '%s' in %s%s"
                            % (declared[0], where or "(no <IconPath>)", hint), clear_after=12000)
        elif all(x.lower().endswith(".svg") for x in located):
            self.set_status("Menu icons are svg files: install rsvg-convert to draw them "
                            "(sudo apt install librsvg2-bin)", clear_after=12000)
        else:
            self.set_status("Menu icons found but they cannot be read (xpm needs python3-pil)",
                            clear_after=12000)

    def _draw_tray(self, w, h, raw, S, C, col):
        # Shared tray renderer used by both the Style and the Background previews.
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
        fonts = raw["fonts"]

        def tbtn(x1, y1_, x2, y2_, spec, pressed=False):
            """Tray element: flat, or raised/sunken when the tray is motif."""
            self._fill(x1, y1_, x2, y2_, spec)
            if tmotif:
                self._bevel(x1, y1_, x2, y2_, spec[0], not pressed, 1)

        icon_fam = self._icon_font(raw["tray_font"])
        is_pua = lambda ch: 0xE000 <= ord(ch) <= 0xF8FF or ord(ch) >= 0xF0000

        def label_of(text):
            lab = text.strip()
            if lab and any(is_pua(ch) for ch in lab) and not icon_fam:
                return "\u2022"                  # Nerd Font symbol not available
            return lab

        tray_font = self._font_tuple(fonts.get("tray"))
        ndesk, cell = 3, int(tray_h * 1.64)
        clock_spec = fonts.get("clock")

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
                return 14 + self._font_obj(clock_spec).measure(self._clock_text(it["format"]))
            if kind == "button":
                if it["action"].startswith("root:"):
                    return int(tray_h * 1.64)
                lab = label_of(it["label"])
                if not lab:
                    return tray_h
                if any(is_pua(ch) for ch in it["label"]):
                    return max(tray_h, 12 + 7 * len(lab))     # symbol buttons
                return 5 + self._font_obj(fonts.get("tray")).measure(lab)   # plain text
            return 0                              # tasklist: takes the remaining space

        items = raw["tray_items"]
        flex = max(90, w - sum(width_of(i) for i in items))
        x = 0
        for it in items:
            kind = it["type"]
            wd = flex if kind == "tasklist" else width_of(it)
            if kind == "button":
                tbtn(x, y1, x + wd, y2, S("tbtn_bg"))
                if it["action"].startswith("root:"):
                    logo = self._logo_image(self._icon_paths_now, wd - 8, tray_h - 8)
                    if logo:
                        c.create_image(x + wd / 2, mid, image=logo)
                    elif icon_fam:
                        c.create_text(x + wd / 2, mid, text=MENU_ICON, fill=C("tbtn_fg"),
                                      font=(icon_fam, 14))
                    else:
                        c.create_text(x + wd / 2, mid, text="JWM", fill=C("tbtn_fg"),
                                      font=tray_font)
                else:
                    lab = label_of(it["label"])
                    photo = self._icon_photo(it["icon"], tray_h - 8) if it["icon"] else None
                    if photo:
                        c.create_image(x + wd / 2, mid, image=photo)
                    elif lab:
                        pua = any(is_pua(ch) for ch in it["label"])
                        c.create_text(x + wd / 2, mid, text=lab, fill=C("tbtn_fg"),
                                      font=(icon_fam, 12) if (pua and icon_fam) else tray_font)
                    else:  # button with an icon that cannot be drawn: placeholder
                        c.create_rectangle(x + wd / 2 - 6, mid - 6, x + wd / 2 + 6, mid + 6,
                                           outline=C("tbtn_fg"))
            elif kind == "pager":
                pager_font = self._font_tuple(fonts.get("pager"))
                for i in range(ndesk):
                    x0, act = x + i * cell, i == 1       # like the real tray: 2nd desktop active
                    left = x0 + 1 if (tmotif and i) else x0
                    self._fill(left, y1, x0 + cell, y2, S("pager_act_bg") if act else S("pager_bg"))
                    if act:  # thumbnail of the active window on the active desktop
                        c.create_rectangle(x0 + 4, y1 + 6, x0 + 26, y2 - 4,
                                           fill=C("pager_act_fg"), outline=C("pager_outline"))
                    elif it.get("labeled"):
                        c.create_text(x0 + cell / 2, mid, text=str(i + 1),
                                      fill=C("pager_text"), font=pager_font)
                    if tmotif:   # thin line between desktops, in the pager outline color
                        if i:
                            c.create_line(x0, y1, x0, y2, fill=C("pager_outline"))
                    else:
                        c.create_rectangle(x0, y1, x0 + cell, y2, outline=C("pager_outline"))
            elif kind == "tasklist":
                task_spec = fonts.get("task")
                task_font = self._font_tuple(task_spec)
                kinds = (("Active window", "task_act_", True), ("Window", "task_", False),
                         ("Minimized", "task_min_", True))
                n = max(1, min(len(kinds), int(wd // 110)))
                iw = max(50, min(it["maxwidth"], int(wd // n)))
                app_icon = self._photo(ICON_FILE, tray_h - 8, tray_h - 8) \
                    if os.path.isfile(ICON_FILE) else None
                for j, (label, pre, pressed) in enumerate(kinds[:n]):
                    ix = x + j * iw                  # items are side by side, no gap
                    tbtn(ix, y1, ix + iw, y2, S(pre + "bg"), pressed=pressed)
                    if app_icon:
                        c.create_image(ix + 4, mid, anchor="w", image=app_icon)
                    else:
                        c.create_rectangle(ix + 5, mid - 5, ix + 15, mid + 5, outline=C(pre + "fg"))
                    shown = self._fit_text(task_spec, label, iw - 30)
                    c.create_text(ix + 25, mid, text=shown, anchor="w", fill=C(pre + "fg"),
                                  font=task_font)
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
                              fill=C("clock_fg"), font=self._font_tuple(clock_spec))
            x += wd


if __name__ == "__main__":
    App().mainloop()
