#!/bin/sh
# Builds MeetDeck-Windows.zip: 32-bit embeddable Python + packages + MeetDeck + starter data.
# 32-bit because Windows' built-in Microsoft Access driver (the one Meet Manager uses) is 32-bit.
# Usage: windows/build.sh [--with-meets]      (run on plex; needs docker + internet)
set -e
cd "$(dirname "$0")/.."
PY=3.12.8
OUT=windows/dist
B=windows/build
rm -rf "$B" && mkdir -p "$B/MeetDeck/python" "$B/MeetDeck/app" "$B/MeetDeck/seed" "$OUT" windows/cache
cd windows/cache
[ -f python-$PY-embed-win32.zip ] || curl -sSfLO https://www.python.org/ftp/python/$PY/python-$PY-embed-win32.zip
cd ../..
python3 -c "import zipfile;zipfile.ZipFile('windows/cache/python-$PY-embed-win32.zip').extractall('$B/MeetDeck/python')"
# packages: Windows 32-bit wheels for Python 3.12, unpacked straight into site-packages
docker run --rm -v "$PWD/windows/cache:/w" python:3.12-slim sh -c \
  "pip download -q --dest /w/wheels --platform win32 --python-version 3.12 --implementation cp --abi cp312 --only-binary=:all: \
   'fastapi==0.115.*' 'uvicorn==0.32.*' 'python-multipart==0.0.*' 'reportlab==4.2.*' tzdata 'pypdf==5.*' pyodbc pystray pillow pyserial colorama certifi"
SP="$B/MeetDeck/python/Lib/site-packages"
mkdir -p "$SP"
for w in windows/cache/wheels/*.whl; do python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$w" "$SP"; done
# wheel .data/platlib and purelib go into site-packages itself (pyodbc ships its C++ runtime there)
for d in "$SP"/*.data/platlib "$SP"/*.data/purelib; do [ -d "$d" ] && cp -r "$d"/. "$SP"/ && rm -rf "$d"; done
# let the embedded Python find site-packages and the app
PTH=$(ls "$B/MeetDeck/python"/python3*._pth)
printf 'python312.zip\n.\nLib\\site-packages\n..\\app\nimport site\n' > "$PTH"
# the app
cp app/*.py app/mmdb_profile.json "$B/MeetDeck/app/"
cp -r app/static "$B/MeetDeck/app/static"
cp -r app/rules_seed "$B/MeetDeck/app/rules_seed"     # official rules documents + AO slides; every copy adds them
mkdir -p "$B/MeetDeck/app/timing" && cp timing/*.py timing/README.txt "timing/Console emulator.bat" "$B/MeetDeck/app/timing/"
cp windows/launcher.py "$B/MeetDeck/app/launcher.py"
mkdir -p "$B/MeetDeck/app/tools" && cp windows/MeetDeck-Launcher.ps1 "$B/MeetDeck/app/tools/"
# "MeetDeck Launcher.exe": a tiny stub with the MeetDeck icon that opens the launcher script
# (source: windows/launcher-exe/launcher.c). Updates carry it in app/tools; the launcher copies it to the root.
cp "windows/launcher-exe/MeetDeck Launcher.exe" "$B/MeetDeck/MeetDeck Launcher.exe"
cp "windows/launcher-exe/MeetDeck Launcher.exe" "$B/MeetDeck/app/tools/MeetDeck Launcher.exe"
cp windows/launcher-exe/MeetDeck.exe "$B/MeetDeck/MeetDeck.exe" && cp windows/launcher-exe/MeetDeck.exe "$B/MeetDeck/app/tools/MeetDeck.exe"
cp "$SP/certifi/cacert.pem" "$B/MeetDeck/app/cacert.pem"     # CA list for HTTPS (updates); travels with app updates
cp windows/start.py "$B/MeetDeck/start.py"
cp windows/start.py "$B/MeetDeck/app/start.py"      # updates carry it; the launcher refreshes the root copy
# icon: app/static/meetdeck.ico / .png / .svg are committed (made from meetdeck.svg)
# starter data: host schools' master meets, rules library, settings (and the meets, if asked)
for f in hosts hosts.json template rules settings.json; do [ -e data/$f ] && cp -r data/$f "$B/MeetDeck/seed/"; done
python3 - "$B/MeetDeck/seed/settings.json" <<'PY'
import json,sys
p=sys.argv[1]; s=json.load(open(p))
for k in ("drive_token","drive_url"): s.pop(k,None)       # Drive write access is set up per PC
json.dump(s,open(p,"w"),indent=1)
PY
[ "$1" = "--with-meets" ] && cp -r data/meets "$B/MeetDeck/seed/meets"
cp windows/README.txt "$B/MeetDeck/README.txt"
printf '@echo off\r\nstart "" "%%~dp0python\\pythonw.exe" -X utf8 "%%~dp0start.py"\r\n' > "$B/MeetDeck/MeetDeck.bat"
printf '@echo off\r\n"%%~dp0python\\python.exe" -X utf8 "%%~dp0start.py" --console\r\npause\r\n' > "$B/MeetDeck/MeetDeck (show log).bat"
printf '@echo off\r\ncd /d "%%~dp0app\\timing"\r\n"%%~dp0python\\python.exe" -X utf8 emulator.py %%*\r\n' > "$B/MeetDeck/CTS console emulator.bat"
printf '@echo off\r\nrem Start/stop MeetDeck and the CTS console tools.\r\nstart "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%%~dp0app\\tools\\MeetDeck-Launcher.ps1"\r\n' > "$B/MeetDeck/MeetDeck Launcher.cmd"
VER=$(cat app/VERSION)
cp app/VERSION "$B/MeetDeck/app/VERSION"
# the update package: just the app folder (what GitHub releases carry)
rm -f "$OUT"/meetdeck-app-*.zip
ZIPOUT="$PWD/$OUT/meetdeck-app-$VER.zip"
(cd "$B/MeetDeck/app" && python3 -c "
import os,zipfile,sys
z=zipfile.ZipFile(sys.argv[1],'w',zipfile.ZIP_DEFLATED)
for r,_,fs in os.walk('.'):
    if '__pycache__' in r: continue
    for f in fs: z.write(os.path.join(r,f), os.path.relpath(os.path.join(r,f),'.'))
z.close()" "$ZIPOUT")
rm -f "$OUT/MeetDeck-Windows.zip"
(cd "$B" && python3 -c "
import os,zipfile
z=zipfile.ZipFile('../dist/MeetDeck-Windows.zip','w',zipfile.ZIP_DEFLATED)
for r,_,fs in os.walk('MeetDeck'):
    for f in fs:
        if '__pycache__' in r: continue
        z.write(os.path.join(r,f))
z.close()")
ls -la "$OUT/MeetDeck-Windows.zip"
docker exec swimmeet mkdir -p /data/downloads && docker cp windows/dist/MeetDeck-Windows.zip swimmeet:/data/downloads/
