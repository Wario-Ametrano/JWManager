#!/bin/sh
# jwmanager-wallpaper.sh - sets the desktop wallpaper for JWM.
#
# JWM does not draw images on its own, so JWManager writes a call to this script into the
# <StartupCommand> and <RestartCommand> of a theme. JWM then runs it every time it starts
# and every time it restarts.
#
# Usage:   jwmanager-wallpaper.sh MODE FILE
#   MODE   tiled | scaled | centered | filled      (the same four styles as feh)
#   FILE   path of a png or jpg image
#
# Install:  copy this file to ~/.jwm/jwmanager-wallpaper.sh
# It needs one of: feh (recommended), xwallpaper, hsetroot.   sudo apt install feh

mode="$1"
file="$2"

if [ -z "$mode" ] || [ -z "$file" ]; then
    echo "usage: $0 tiled|scaled|centered|filled FILE" >&2
    exit 2
fi

if [ ! -f "$file" ]; then
    echo "jwmanager-wallpaper: file not found: $file" >&2
    exit 1
fi

if command -v feh >/dev/null 2>&1; then
    case "$mode" in
        tiled)    exec feh --no-fehbg --bg-tile   "$file" ;;
        scaled)   exec feh --no-fehbg --bg-scale  "$file" ;;
        centered) exec feh --no-fehbg --bg-center "$file" ;;
        *)        exec feh --no-fehbg --bg-fill   "$file" ;;
    esac
elif command -v xwallpaper >/dev/null 2>&1; then
    case "$mode" in
        tiled)    exec xwallpaper --tile    "$file" ;;
        scaled)   exec xwallpaper --stretch "$file" ;;
        centered) exec xwallpaper --center  "$file" ;;
        *)        exec xwallpaper --zoom    "$file" ;;
    esac
elif command -v hsetroot >/dev/null 2>&1; then
    case "$mode" in
        tiled)    exec hsetroot -tile   "$file" ;;
        scaled)   exec hsetroot -fill   "$file" ;;
        centered) exec hsetroot -center "$file" ;;
        *)        exec hsetroot -full   "$file" ;;
    esac
fi

echo "jwmanager-wallpaper: install feh (sudo apt install feh), xwallpaper or hsetroot" >&2
exit 1
