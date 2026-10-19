# JWManager


A small graphical program to **switch themes in JWM** without having to edit your `~/.jwmrc` file by hand every time. Pick a theme from the list, check the preview, press **Apply**, and JWM instantly reloads with the new theme.

![Dark](https://github.com/Wario-Ametrano/JWManager/blob/main/.jwm/screenshot.png)

## Features

- Shows a **list of themes** stored in the `~/.jwm/themes` folder.
- Shows a **preview** (active and inactive window, menu, panel, pager, clock) that changes with each selected theme.
- **Apply** a theme: copies its file to `~/.jwmrc` and restarts JWM.
- **Reset default** to go back to your original configuration.
- Reproduces both JWM looks: **motif** (retro, raised Windows 98-style bevels, `decorations="motif"`) and **flat** (no bevels, the default when the attribute is missing).
- The app **takes on the look of the theme you applied**: its colors and button style follow your JWM theme (see below).

## Requirements

- Ubuntu (or another Linux distribution) running **JWM** as the desktop environment
- **Python 3**
- **Tkinter** (Python's graphical library)

Optional, only to show the JWM logo in the preview: **Pillow**. The app's own icon is built into the program and needs nothing.

## Installation

### 1. Install the required packages

Open a terminal and run:

```bash
sudo apt update
sudo apt install python3 python3-tk
```

Optional (logo in the preview):

```bash
sudo apt install python3-pil python3-pil.imagetk
```

### 2. Download the program

With git:

```bash
git clone https://github.com/YOUR-USERNAME/REPOSITORY-NAME.git
cd REPOSITORY-NAME
```

Or download the `jwmaneger.py` file from the project's GitHub page (green **Code → Download ZIP** button).

### 3. Put it in the JWM folder

```bash
mkdir -p ~/.jwm
cp jwmaneger.py ~/.jwm/
chmod +x ~/.jwm/jwmaneger.py
```

## Running

From a terminal:

```bash
python3 ~/.jwm/jwmaneger.py
```

Launch from the JWM menu (recommended)
```xml
<Program icon="/home/YOUR-USER/.jwm/icons/jwmaneger.png" label="jwmaneger">python3 ~/.jwm/jwmaneger.py</Program>
```
### Adding a new theme

1. Create a folder with the theme name:
   ```bash
   mkdir -p ~/.jwm/themes/dark
   ```
2. Copy the theme file into it, naming it `.jwmrc`:
   ```bash
   cp my-theme.jwmrc ~/.jwm/themes/dark/.jwmrc
   ```
3. In the program, press **Reload list**.

   To save the configuration you are using right now as a theme:

   ```bash
   mkdir -p ~/.jwm/themes/my-theme
   cp ~/.jwmrc ~/.jwm/themes/my-theme/.jwmrc
   ```

### Using the program

1. **Select a theme** in the list on the left: the preview on the right updates.
2. Press **Apply** (or double-click the theme).
3. JWM restarts and the new theme is active.
4. To go back, press **Reset default**.

### What happens when you press "Apply"

1. Your current `~/.jwmrc` is saved as `~/.jwmrc.bak` (safety copy).
2. The file `~/.jwm/themes/<theme>/.jwmrc` is copied to `~/.jwmrc`.
3. The program checks that the copy is identical to the original.
4. JWM is restarted with `jwm -restart`.

## Troubleshooting

The program won't start and shows `No module named 'tkinter'`Install Tkinter: `sudo apt install python3-tk`
I press "Apply" but the theme doesn't change
Read the message below the preview. Then try by hand:
```bash
cp ~/.jwm/themes/THEME-NAME/.jwmrc ~/.jwmrc
jwm -restart
```
If that works, check that the `jwm` command is in your PATH (`which jwm`).
**A theme doesn't show up in the list**
Check that the file `~/.jwm/themes/THEME-NAME/.jwmrc` exists (with the leading dot) and press **Reload list**. Folders starting with a dot are ignored.
**The logo doesn't appear**
Put a `png` named `jwm-logo.png` in `~/.jwm/`. (Files starting with `jwmaneger`, like the app icon, are never used as the JWM logo.)

## Uninstall

```bash
rm ~/.jwm/jwmaneger.py ~/.jwm/jwmaneger-cache.json
```

Your themes in `~/.jwm/themes` stay where they are.
