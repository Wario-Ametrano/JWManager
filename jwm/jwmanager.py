#!/usr/bin/env python3
"""JWM Theme Manager - gestione temi per JWM con anteprima.

Ogni tema e' una cartella dentro ~/.jwm/themes che contiene un file .jwmrc:
    ~/.jwm/themes/<nome-tema>/.jwmrc
Il nome del tema e' il nome della cartella. Premendo "Applica" il file
viene copiato in ~/.jwmrc e JWM viene riavviato.
"""
import os
import re
import filecmp
import glob
import shutil
import subprocess
import traceback
import tkinter as tk
import tkinter.font as tkfont
import xml.etree.ElementTree as ET

HOME = os.path.expanduser("~")
THEMES_DIR = os.path.join(HOME, ".jwm", "themes")
TARGET = os.path.join(HOME, ".jwmrc")
THEME_FILE = ".jwmrc"
DEFAULT_NAME = "default"

# Simbolo (Nerd Font) mostrato sul pulsante menu della barra nell'anteprima.
# Per cambiarlo: metti il codice del simbolo, es. "\uf17b8" oppure "\ue795".
# Se nessun Nerd Font e' installato, l'anteprima ripiega sulla scritta "JWM".
MENU_ICON = "\uebc6"
SYSTEM_RC = "/etc/jwm/system.jwmrc"

# Colori dell'interfaccia (minimale, nera)
BG = "#000000"
FG = "#d8d8d8"
ACCENT = "#3a3a3a"
SEL = "#e0e0e0"


# ---------------------------------------------------------------- parsing
_ENTITY_BAD = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
_ATTR_GAP = re.compile(r'(=\s*"[^"]*")(?=[A-Za-z_])')
_TAG = re.compile(r"<[A-Za-z/][^<>]*>")


def read_xml(path):
    """Legge un .jwmrc in modo tollerante.

    JWM accetta file che un parser XML rigoroso rifiuta, ad esempio:
    '&' non codificati nel testo, attributi senza spazio (x="0"y="-1").
    Qui li correggiamo prima di leggere il file.
    """
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)       # commenti
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)           # dichiarazione
    text = _TAG.sub(lambda m: _ATTR_GAP.sub(r"\1 ", m.group(0)), text)
    text = _ENTITY_BAD.sub("&amp;", text)
    return ET.fromstring(text)


def load_roots(path, depth=0, seen=None):
    """Carica il file e, ricorsivamente, i file inclusi con <Include>."""
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
            pass  # un menu incluso puo' non essere XML valido: lo ignoriamo
    return roots


def split_grad(spec):
    """'#aaa:#bbb' -> ['#aaa', '#bbb'] (gradiente). 'rgb:..' non e' un gradiente."""
    spec = spec.strip()
    if spec.lower().startswith("rgb:"):
        return [spec]
    return [x.strip() for x in spec.split(":") if x.strip()][:2]


# chiave -> percorsi XML possibili (il primo trovato vince)
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

# colori usati se il tema non definisce nulla
DEFAULT_COLORS = {
    "desktop": "#2b2b2b", "tray_bg": "#333333", "tray_fg": "#ffffff",
    "act_title": "#444444", "act_text": "#ffffff",
    "inact_title": "#222222", "inact_text": "#999999",
    "menu_bg": "#333333", "menu_fg": "#ffffff",
}
# colore mancante -> eredita da un altro colore del tema
FALLBACK = {
    "tray_outline": "tray_bg", "tray_act_bg": "tray_fg", "tray_act_fg": "tray_bg",
    "act_outline": "act_title", "inact_outline": "inact_title",
    "menu_outline": "menu_bg", "menu_sel_bg": "menu_fg", "menu_sel_fg": "menu_bg",
    "task_bg": "tray_bg", "task_fg": "tray_fg",
    "task_act_bg": "task_bg", "task_act_fg": "task_fg",
    "clock_bg": "tray_bg", "clock_fg": "tray_fg",
    "pager_bg": "tray_bg", "pager_fg": "tray_fg", "pager_outline": "tray_bg",
    "pager_text": "tray_fg", "pager_act_bg": "pager_fg", "pager_act_fg": "pager_bg",
}


def parse_theme(path):
    """Estrae colori e misure principali da un file .jwmrc (formati 2.3 e 2.4)."""
    t = {"tray_pos": "bottom", "tray_h": 28, "title_h": 22, "border": 1,
         "font": "", "tray_font": "", "icon_paths": [], "note": "", "error": None, "found": 0, "colors": {}}
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
                            t["note"] = "sfondo di tipo '%s' non mostrato" % kind
                            continue
                    t["colors"][key] = val
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


LOGO_EXT = (".png", ".gif", ".ppm", ".xpm", ".jpg", ".jpeg", ".bmp")


def find_logo(icon_paths):
    """Cerca il logo di JWM. Ordine: ~/.jwm/jwm-logo.*, IconPath del tema,
    ~/.jwm/icons, pixmaps e icone di sistema. Vince il primo file jwm*.<ext>."""
    dirs = [os.path.join(HOME, ".jwm")]
    dirs += [os.path.expanduser(p) for p in icon_paths]
    dirs += [os.path.join(HOME, ".jwm", "icons"), "/usr/share/pixmaps",
             "/usr/local/share/pixmaps", "/usr/share/jwm", "/usr/share/icons/hicolor/*/apps",
             "/usr/share/icons/*/*/apps"]
    for ext in LOGO_EXT:
        for d in dirs:
            names = ["jwm-logo*", "jwm*"] if d == dirs[0] else ["jwm*"]
            for n in names:
                for f in sorted(glob.glob(os.path.join(d, n + ext))):
                    if os.path.isfile(f):
                        return f
    return None


def font_family(spec):
    """'JetBrainsMono NL Nerd Font-10' / 'Fam:pixelsize=14' -> nome famiglia."""
    spec = (spec or "").strip()
    if not spec:
        return ""
    fam = spec.split(":")[0]
    m = re.match(r"^(.*?)-\d+(\.\d+)?$", fam)
    return (m.group(1) if m else fam).strip()


# ----------------------------------------------------------------- logica
def theme_path(name):
    return os.path.join(THEMES_DIR, name, THEME_FILE)


def ensure_setup():
    os.makedirs(THEMES_DIR, exist_ok=True)
    default_path = theme_path(DEFAULT_NAME)
    if not os.path.exists(default_path):
        # Salva la configurazione attuale come tema "default"
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
    # il default sempre in cima
    if DEFAULT_NAME in files:
        files.remove(DEFAULT_NAME)
        files.insert(0, DEFAULT_NAME)
    return files


def reload_jwm():
    """Riavvia JWM. Restituisce (ok, messaggio_errore)."""
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    last = ""
    for opt in ("-restart", "-reload"):
        try:
            r = subprocess.run(["jwm", opt], env=env, capture_output=True,
                               text=True, timeout=10)
        except FileNotFoundError:
            return False, "comando 'jwm' non trovato nel PATH"
        except Exception as e:
            last = str(e)
            continue
        if r.returncode == 0:
            return True, ""
        last = (r.stderr or r.stdout or "codice %d" % r.returncode).strip()
    return False, last


# -------------------------------------------------------------------- GUI
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("JWM Theme Manager")
        self.configure(bg=BG)
        self.geometry("760x460")
        self.minsize(640, 400)

        ensure_setup()

        left = tk.Frame(self, bg=BG)
        left.pack(side="left", fill="y", padx=(12, 6), pady=12)
        right = tk.Frame(self, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(6, 12), pady=12)

        tk.Label(left, text="TEMI", bg=BG, fg=FG, font=("Sans", 10, "bold"),
                 anchor="w").pack(fill="x", pady=(0, 6))

        self.listbox = tk.Listbox(
            left, bg=BG, fg=FG, selectbackground=SEL, selectforeground="#000000",
            highlightthickness=1, highlightbackground=ACCENT, highlightcolor=ACCENT,
            relief="flat", bd=0, activestyle="none", width=24, font=("Sans", 10),
            exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.on_select())
        self.listbox.bind("<Double-Button-1>", lambda e: self.apply())

        btns = tk.Frame(left, bg=BG)
        btns.pack(fill="x", pady=(10, 0))
        self.btn(btns, "Applica", self.apply).pack(fill="x", pady=2)
        self.btn(btns, "Ripristina default", self.reset).pack(fill="x", pady=2)
        self.btn(btns, "Ricarica lista", self.refresh).pack(fill="x", pady=2)

        tk.Label(right, text="ANTEPRIMA", bg=BG, fg=FG, font=("Sans", 10, "bold"),
                 anchor="w").pack(fill="x", pady=(0, 6))
        self.canvas = tk.Canvas(right, bg=BG, highlightthickness=1,
                                highlightbackground=ACCENT, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw())

        self.status = tk.Label(right, text="", bg=BG, fg="#8a8a8a", anchor="w",
                               justify="left", wraplength=440, font=("Sans", 9))
        self.status.pack(fill="x", pady=(8, 0))

        self.theme = None
        self.current = None
        self.refresh()
        self.listbox.focus_set()
        self.after(150, self._poll)

    def report_callback_exception(self, exc, val, tb):
        """Mostra gli errori nella barra di stato invece di perderli."""
        traceback.print_exception(exc, val, tb)
        self.set_status("ERRORE: %s: %s" % (exc.__name__, val))

    def _poll(self):
        """Controlla la selezione anche se l'evento della lista non arriva."""
        try:
            sel = self.listbox.curselection()
            if sel and self.listbox.get(sel[0]) != self.current:
                self.on_select()
        except Exception as e:
            self.set_status("ERRORE: %s" % e)
        self.after(150, self._poll)

    def btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=BG, fg=FG,
                         activebackground=SEL, activeforeground="#000000",
                         relief="flat", bd=0, highlightthickness=1,
                         highlightbackground=ACCENT, highlightcolor=FG,
                         padx=8, pady=6, cursor="hand2")

    # -- azioni
    def refresh(self):
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
            self.set_status("Nessun tema trovato in %s (serve <tema>/.jwmrc)" % THEMES_DIR)

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
        self.theme = parse_theme(theme_path(name))
        if self.theme["error"]:
            msg = "Errore nel file: " + self.theme["error"]
        else:
            msg = "%s  (colori letti: %d/%d)" % (name, self.theme["found"], len(COLOR_PATHS))
            if self.theme["note"]:
                msg += " - " + self.theme["note"]
        self.set_status(msg)
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
                raise IOError("il file copiato non coincide con l'originale")
        except Exception as e:
            self.set_status("Errore copia: %s" % e)
            return
        ok, err = reload_jwm()
        if ok:
            msg = "Applicato: %s  ->  %s" % (name, TARGET)
        else:
            msg = "Copiato in %s ma riavvio JWM fallito: %s" % (TARGET, err)
        print(msg, flush=True)
        self.set_status(msg)

    def apply(self):
        name = self.selected()
        if not name:
            self.set_status("Seleziona prima un tema nella lista")
            return
        self.set_status("Applico %s ..." % name)
        self.update_idletasks()
        self.apply_file(name)

    def reset(self):
        if not os.path.exists(theme_path(DEFAULT_NAME)):
            self.set_status("Tema '%s' non trovato" % DEFAULT_NAME)
            return
        self.apply_file(DEFAULT_NAME)
        items = list(self.listbox.get(0, "end"))
        if DEFAULT_NAME in items:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(items.index(DEFAULT_NAME))
            self.on_select()

    # -- anteprima
    def _valid(self, color):
        try:
            self.winfo_rgb(color)
            return True
        except tk.TclError:
            return False

    def _spec(self, colors, key):
        """Restituisce (colore1, colore2|None) per la chiave, con ereditarieta'."""
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
        """Rettangolo pieno oppure sfumato (gradiente) tra due colori."""
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

    def _ui_font(self, raw):
        fam = font_family(raw)
        try:
            if fam and fam in set(tkfont.families(self)):
                return fam
        except Exception:
            pass
        return "Sans"

    def _logo_image(self, icon_paths, size):
        """Immagine del logo ridimensionata (None se non si trova/non si legge)."""
        cache = self.__dict__.setdefault("_logo_cache", {})
        path = find_logo(icon_paths)
        key = (path, size)
        if key in cache:
            return cache[key]
        img = None
        if path:
            try:  # con Pillow: tutti i formati, ridimensionamento di qualita'
                from PIL import Image, ImageTk
                im = Image.open(path).convert("RGBA")
                try:
                    resample = Image.Resampling.LANCZOS
                except AttributeError:
                    resample = Image.LANCZOS
                im.thumbnail((size, size), resample)
                img = ImageTk.PhotoImage(im, master=self)
            except Exception:
                try:  # senza Pillow: Tk legge solo png/gif/ppm
                    raw = tk.PhotoImage(file=path, master=self)
                    f = max(1, -(-max(raw.width(), raw.height()) // size))
                    img = raw.subsample(f) if f > 1 else raw
                except Exception:
                    img = None
        cache[key] = img
        return img

    def _icon_font(self, tray_font):
        """Cerca un Nerd Font installato (preferendo quello della tray)."""
        try:
            fams = list(tkfont.families(self))
        except Exception:
            return None
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
        S = lambda key: self._spec(col, key)       # (c1, c2)
        C = lambda key: self._spec(col, key)[0]    # solo colore principale
        fam = self._ui_font(raw["font"])
        F = lambda size=9, bold=False: (fam, size, "bold") if bold else (fam, size)

        tray_h = raw["tray_h"]
        top_tray = raw["tray_pos"] == "top"
        ay1 = tray_h if top_tray else 0            # area utile (senza tray)
        ay2 = h if top_tray else h - tray_h
        H = ay2 - ay1

        # sfondo desktop (solido o sfumato verticale)
        self._fill(0, 0, w, h, S("desktop"), vertical=True)

        bw = raw["border"]
        th = raw["title_h"]

        def window(x, y, ww, hh, active, label):
            pre = "act" if active else "inact"
            outline = C(pre + "_outline")
            c.create_rectangle(x, y, x + ww, y + hh, fill=outline, outline="")
            self._fill(x + bw, y + bw, x + ww - bw, y + bw + th, S(pre + "_title"))
            c.create_rectangle(x + bw, y + bw + th, x + ww - bw, y + hh - bw,
                               fill="#1e1e1e", outline="")
            txt = C(pre + "_text")
            c.create_text(x + bw + 8, y + bw + th / 2, text=label, anchor="w",
                          fill=txt, font=F(9, active))
            # pulsanti in alto a destra: minimizza, massimizza, chiudi
            cy = y + bw + th / 2
            r = 4
            cx = x + ww - bw - 14                      # chiudi (X)
            c.create_line(cx - r, cy - r, cx + r + 1, cy + r + 1, fill=txt, width=1)
            c.create_line(cx - r, cy + r, cx + r + 1, cy - r - 1, fill=txt, width=1)
            cx -= 20                                   # massimizza (quadrato)
            c.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline=txt)
            cx -= 20                                   # minimizza (trattino)
            c.create_line(cx - r, cy + r - 1, cx + r + 1, cy + r - 1, fill=txt, width=2)
            c.create_text(x + bw + 10, y + bw + th + 18, text="Contenuto della finestra",
                          anchor="w", fill="#9a9a9a", font=F(9))

        window(w * 0.05, ay1 + H * 0.10, w * 0.46, H * 0.40, False, "Finestra inattiva")
        window(w * 0.20, ay1 + H * 0.34, w * 0.50, H * 0.46, True, "Finestra attiva")

        # menu
        mx, my, mw = w * 0.72, ay1 + H * 0.08, min(w * 0.25, 170)
        items = ("Terminale", "Browser", "Esci")
        ih = 24
        c.create_rectangle(mx, my, mx + mw, my + ih * len(items) + 4,
                           fill=C("menu_outline"), outline="")
        self._fill(mx + 1, my + 1, mx + mw - 1, my + ih * len(items) + 3, S("menu_bg"))
        for i, label in enumerate(items):
            iy = my + 2 + i * ih
            if i == 1:
                self._fill(mx + 2, iy, mx + mw - 2, iy + ih, S("menu_sel_bg"))
                fg = C("menu_sel_fg")
            else:
                fg = C("menu_fg")
            c.create_text(mx + 10, iy + ih / 2, text=label, anchor="w", fill=fg, font=F(9))

        # tray
        ty = 0 if top_tray else h - tray_h
        self._fill(0, ty, w, ty + tray_h, S("tray_bg"), vertical=True)
        c.create_line(0, ty + (tray_h - 1 if top_tray else 0), w,
                      ty + (tray_h - 1 if top_tray else 0), fill=C("tray_outline"))
        mid = ty + tray_h / 2
        # pulsante menu con il simbolo (colori "Active" della tray)
        logo = self._logo_image(raw["icon_paths"], tray_h - 8)
        icon_fam = self._icon_font(raw["tray_font"])
        bwid = max(34, tray_h * 1.3) if (logo or icon_fam) else max(44, tray_h * 1.7)
        self._fill(2, ty + 2, 2 + bwid, ty + tray_h - 2, S("tray_act_bg"))
        if logo:
            c.create_image(2 + bwid / 2, mid, image=logo)
        elif icon_fam:
            c.create_text(2 + bwid / 2, mid, text=MENU_ICON, fill=C("tray_act_fg"),
                          font=(icon_fam, 14))
        else:
            c.create_text(2 + bwid / 2, mid, text="JWM", fill=C("tray_act_fg"),
                          font=F(9, True))
        # pager: 2 desktop, il primo attivo
        px = 2 + bwid + 10
        for i in range(2):
            act = i == 0
            bg = S("pager_act_bg") if act else S("pager_bg")
            self._fill(px, ty + 3, px + 34, ty + tray_h - 3, bg, outline=C("pager_outline"))
            c.create_rectangle(px + 6, ty + 8, px + 22, ty + tray_h - 8,
                               fill=C("pager_act_fg" if act else "pager_fg"), outline="")
            c.create_text(px + 28, mid, text=str(i + 1), fill=C("pager_text"), font=F(8))
            px += 36
        # lista finestre: una attiva, una no
        tx = px + 10
        tw = min(150, max(70, (w - tx - 90) / 2 - 6))
        for label, act in (("Finestra attiva", True), ("Finestra", False)):
            p = "task_act_" if act else "task_"
            self._fill(tx, ty + 3, tx + tw, ty + tray_h - 3, S(p + "bg"))
            c.create_text(tx + 6, mid, text=label, anchor="w", fill=C(p + "fg"), font=F(8))
            tx += tw + 6
        # orologio
        cw = 56
        self._fill(w - cw - 4, ty + 3, w - 4, ty + tray_h - 3, S("clock_bg"))
        c.create_text(w - 4 - cw / 2, mid, text="12:34", fill=C("clock_fg"), font=F(9))


if __name__ == "__main__":
    App().mainloop()
