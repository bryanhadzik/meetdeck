"""Make the PUBLIC installer (MeetDeck-Windows.zip for GitHub releases) from the full build.

The full build carries seed data for Bryan's own install: real meets (swimmer names), host
master databases, the rules library (incl. a purchased manual) and settings with the Drive
folder id. None of that may go on public GitHub, so it is left out here; only the empty
Meet Manager template the app needs to build databases stays."""
import sys, zipfile
src, dst = sys.argv[1], sys.argv[2]
DROP = ("MeetDeck/seed/meets/", "MeetDeck/seed/hosts/", "MeetDeck/seed/rules/",
        "MeetDeck/seed/hosts.json", "MeetDeck/seed/settings.json")
n = 0
with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
    for info in zi.infolist():
        if info.filename.startswith(DROP):
            continue
        zo.writestr(info, zi.read(info.filename))
        n += 1
print("public zip:", dst, n, "files")
