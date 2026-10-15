# JWManager

A small graphical program to **switch themes in JWM** without having to edit your `~/.jwmrc` file by hand every time.

Pick a theme from the list, check the preview, press **Apply**, and JWM instantly reloads with the new theme.

### JWM Theme Manager
<img width="857" height="580" alt="screenshot" src="https://github.com/user-attachments/assets/c6e248be-3a6d-4cf7-b769-28609ddbd561" />


## Features

- Shows a **list of themes** stored in the `~/.jwm/themes` folder.
- Shows a **preview** (active and inactive window, menu, panel, pager, clock) that changes with each selected theme.
- **Apply** a theme: copies its file to `~/.jwmrc` and restarts JWM.
- **Reset default** to go back to your original configuration.
- Minimal, all-black interface.

## Requirements

- Ubuntu (or another Linux distribution) running **JWM** as the desktop environment
- **Python 3**
- **Tkinter** (Python's graphical library)

Optional, only to show the JWM logo in the preview: **Pillow**.

## Installation

### 1. Install the required packages

Open a terminal and run:
```bash
sudo apt update
sudo apt install python3 python3-tk
```

### 2. Download the program
With git:

```bash
git clone https://github.com/YOUR-USERNAME/REPOSITORY-NAME.git
cd REPOSITORY-NAME
```
Or download the `jwmanager.py` file from the project's GitHub page (green **Code → Download ZIP** button).

### 3. Put it in the JWM folder

```bash
mkdir -p ~/.jwm
cp jwmanager.py ~/.jwm/
chmod +x ~/.jwm/jwmanager.py
```
## Running

From a terminal:

```bash
python3 ~/.jwm/jwmaneger.py
```

### Launch from the JWM menu (recommended)

Open your `~/.jwmrc` and add this line inside `<RootMenu>`:

```xml
<Program label="JWM Themes">python3 ~/.jwm/jwmanager.py</Program>
```

Then reload JWM and you will find the **JWM Themes** entry in the menu.

### The themes folder

Each theme is a **folder** inside `~/.jwm/themes`, and **the folder name is the theme name**. Inside the folder there is a file named exactly `.jwmrc`:

```
~/.jwm/themes/
├── default/
│   └── .jwmrc
├── penguin/
│   └── .jwmrc
└── dark/
    └── .jwmrc
```

JWM only reads a file named `.jwmrc` in your home folder. That is why each theme lives in its own folder: all the files can have the same name without overwriting each other.

### First launch

On first launch the program creates the `~/.jwm/themes` folder and saves your current configuration as the **default** theme. If you don't have a `~/.jwmrc`, it uses the system one (`/etc/jwm/system.jwmrc`).

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

Below the preview there is a status line with the theme name, the number of colors read from the file (for example `default (colors read: 20/29)`), and the result of the operation (`Applied: ...`).

### What happens when you press "Apply"

1. Your current `~/.jwmrc` is saved as `~/.jwmrc.bak` (safety copy).
2. The file `~/.jwm/themes/<theme>/.jwmrc` is copied to `~/.jwmrc`.
3. The program checks that the copy is identical to the original.
4. JWM is restarted with `jwm -restart`.

## Troubleshooting

**The program won't start and shows `No module named 'tkinter'`**
Install Tkinter: `sudo apt install python3-tk`

Your themes in `~/.jwm/themes` stay where they are.
