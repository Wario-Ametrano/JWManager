#!/usr/bin/env python3
"""JWManager - gestione temi per JWM con anteprima.

Ogni tema e' una cartella dentro ~/.jwm/themes che contiene un file .jwmrc:
    ~/.jwm/themes/<nome-tema>/.jwmrc
Il nome del tema e' il nome della cartella. Premendo "Applica" il file
viene copiato in ~/.jwmrc e JWM viene riavviato.
"""
import os
import filecmp
import shutil
import subprocess
import traceback
import tkinter as tk
import xml.etree.ElementTree as ET

HOME = os.path.expanduser("~")
THEMES_DIR = os.path.join(HOME, ".jwm", "themes")
TARGET = os.path.join(HOME, ".jwmrc")
THEME_FILE = ".jwmrc"
DEFAULT_NAME = "default"
SYSTEM_RC = "/etc/jwm/system.jwmrc"

# Colori dell'interfaccia (minimale, nera)
BG = "#000000"
FG = "#d8d8d8"
ACCENT = "#3a3a3a"
SEL = "#e0e0e0"


# ---------------------------------------------------------------- parsing
def first_color(value):
    """JWM accetta 'colore1:colore2' (gradiente): usiamo il primo.
    Attenzione: 'rgb:ff/00/00' contiene ':' ma non e' un gradiente."""
    v = value.strip()
    if v.lower().startswith("rgb:"):
        return v
    return v.split(":")[0].strip()


def load_roots(path, depth=0, seen=None):
    """Carica il file e, ricorsivamente, i file inclusi con <Include>."""
    seen = seen if seen is not None else set()
    path = os.path.abspath(os.path.expanduser(path))
    if path in seen or depth > 3 or not os.path.isfile(path):
        return []
    seen.add(path)
    root = ET.parse(path).getroot()
    roots = [root]
    for inc in root.iter("Include"):
        target = (inc.text or "").strip()
        if not target or target.startswith("exec:"):
            continue
        if not os.path.isabs(os.path.expanduser(target)):
            target = os.path.join(os.path.dirname(path), target)
        try:
            roots += load_roots(target, depth + 1, seen)
        except Exception:
            pass
    return roots


def parse_theme(path):
    """Estrae i colori principali da un file .jwmrc (formati JWM 2.3 e 2.4)."""
    t = {"tray_pos": "bottom", "error": None, "found": 0, "colors": {}}
    try:
        roots = load_roots(path)
    except Exception as e:  # file non valido
        t["error"] = str(e)
        return t

    def pick(key, paths):
        for root in roots:
            for p in paths:
                for el in root.iterfind(p):
                    if el.text and el.text.strip():
                        t["colors"][key] = first_color(el.text)
                        t["found"] += 1
                        return

    pick("desktop", [".//Desktops/Background"])
    pick("tray_bg", ["TrayStyle/Background", "TrayStyle/Active/Background"])
    pick("tray_fg", ["TrayStyle/Foreground", "TrayStyle/Active/Foreground",
                     "TrayStyle/Active/Text"])
    pick("win_title", ["WindowStyle/Active/Title", "WindowStyle/Active/Background",
                       "WindowStyle/Background"])
    pick("win_text", ["WindowStyle/Active/Text", "WindowStyle/Active/Foreground",
                      "WindowStyle/Foreground"])
    pick("inact_title", ["WindowStyle/Inactive/Title", "WindowStyle/Inactive/Background"])
    pick("inact_text", ["WindowStyle/Inactive/Text", "WindowStyle/Inactive/Foreground"])
    pick("menu_bg", ["MenuStyle/Background"])
    pick("menu_fg", ["MenuStyle/Foreground", "MenuStyle/Text"])
    pick("menu_sel_bg", ["MenuStyle/Active/Background"])
    pick("menu_sel_fg", ["MenuStyle/Active/Foreground", "MenuStyle/Active/Text"])
    pick("task_bg", ["TaskListStyle/Active/Background", "TaskListStyle/Background"])
    pick("task_fg", ["TaskListStyle/Active/Foreground", "TaskListStyle/Foreground",
                     "TaskListStyle/Active/Text"])
    pick("clock_fg", ["ClockStyle/Foreground", "ClockStyle/Text"])

    for root in roots:
        tray = root.find("Tray")
        if tray is not None:
            va = (tray.get("valign") or tray.get("y") or "").lower()
            if va in ("top", "0"):
                t["tray_pos"] = "top"
            break
    return t


DEFAULT_COLORS = {
    "desktop": "#2b2b2b", "tray_bg": "#333333", "tray_fg": "#ffffff",
    "win_title": "#444444", "win_text": "#ffffff",
    "inact_title": "#222222", "inact_text": "#999999",
    "menu_bg": "#333333", "menu_fg": "#ffffff",
    "menu_sel_bg": "#555555", "menu_sel_fg": "#ffffff",
    "task_bg": "#444444", "task_fg": "#ffffff", "clock_fg": "#ffffff",
}
# se manca un colore, eredita da un altro prima di usare il default
INHERIT = {"task_fg": "tray_fg", "clock_fg": "tray_fg"}


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
            msg = "%s  (colori letti: %d/%d)" % (name, self.theme["found"], len(DEFAULT_COLORS))
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
    def draw(self):
        c = self.canvas
        c.delete("all")
        raw = self.theme
        if not raw:
            return
        t = {"tray_pos": raw["tray_pos"]}
        for key, default in DEFAULT_COLORS.items():
            val = raw["colors"].get(key) or raw["colors"].get(INHERIT.get(key, ""), "")
            try:
                self.winfo_rgb(val)  # colore valido per Tk?
            except tk.TclError:
                val = default
            t[key] = val
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50 or h < 50:
            return
        tray_h = 30
        top = tray_h if t["tray_pos"] == "top" else 0
        bot = h - tray_h if t["tray_pos"] != "top" else h

        # desktop
        c.create_rectangle(0, 0, w, h, fill=t["desktop"], outline="")

        # finestra inattiva
        c.create_rectangle(w * 0.08, top + 30, w * 0.55, top + 30 + 110,
                           fill="#1c1c1c", outline=t["inact_title"])
        c.create_rectangle(w * 0.08, top + 30, w * 0.55, top + 52,
                           fill=t["inact_title"], outline="")
        c.create_text(w * 0.08 + 8, top + 41, text="Finestra inattiva", anchor="w",
                      fill=t["inact_text"], font=("Sans", 9))

        # finestra attiva
        x1, y1, x2, y2 = w * 0.25, top + 80, w * 0.75, top + 80 + 130
        c.create_rectangle(x1, y1, x2, y2, fill="#202020", outline=t["win_title"])
        c.create_rectangle(x1, y1, x2, y1 + 24, fill=t["win_title"], outline="")
        c.create_text(x1 + 8, y1 + 12, text="Finestra attiva", anchor="w",
                      fill=t["win_text"], font=("Sans", 9, "bold"))
        for i, bx in enumerate((x2 - 16, x2 - 34, x2 - 52)):
            c.create_rectangle(bx - 6, y1 + 6, bx + 6, y1 + 18, outline=t["win_text"])
        c.create_text(x1 + 10, y1 + 45, text="Contenuto della finestra", anchor="w",
                      fill="#b0b0b0", font=("Sans", 9))

        # menu
        mx, my, mw = w * 0.62, top + 20, 130
        c.create_rectangle(mx, my, mx + mw, my + 78, fill=t["menu_bg"], outline=t["win_title"])
        items = ("Terminale", "Browser", "Esci")
        for i, label in enumerate(items):
            iy = my + 4 + i * 23
            if i == 1:
                c.create_rectangle(mx + 2, iy, mx + mw - 2, iy + 22, fill=t["menu_sel_bg"], outline="")
                col = t["menu_sel_fg"]
            else:
                col = t["menu_fg"]
            c.create_text(mx + 10, iy + 11, text=label, anchor="w", fill=col, font=("Sans", 9))

        # tray
        ty = 0 if t["tray_pos"] == "top" else h - tray_h
        c.create_rectangle(0, ty, w, ty + tray_h, fill=t["tray_bg"], outline="")
        c.create_text(10, ty + tray_h / 2, text="Menu", anchor="w", fill=t["tray_fg"],
                      font=("Sans", 9, "bold"))
        c.create_rectangle(70, ty + 4, 190, ty + tray_h - 4, fill=t["task_bg"], outline="")
        c.create_text(78, ty + tray_h / 2, text="Finestra attiva", anchor="w",
                      fill=t["task_fg"], font=("Sans", 8))
        c.create_text(w - 10, ty + tray_h / 2, text="12:34", anchor="e",
                      fill=t["clock_fg"], font=("Sans", 9))


if __name__ == "__main__":
    App().mainloop()
