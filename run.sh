#!/usr/bin/env bash
# Usa o gtk-layer-shell instalado no sistema ou, se não houver, o extraído em vendor/
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/vendor/root/usr/lib/x86_64-linux-gnu"
if [ -f "$LIB/libgtk-layer-shell.so.0" ]; then
  export GI_TYPELIB_PATH="$LIB/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
  export LD_LIBRARY_PATH="$LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export LD_PRELOAD="$LIB/libgtk-layer-shell.so.0${LD_PRELOAD:+:$LD_PRELOAD}"
fi
exec python3 "$HERE/island.py" "$@"
