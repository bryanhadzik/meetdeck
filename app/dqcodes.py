"""Disqualification codes - the USA Swimming set Meet Manager uses by default (Hy-Tek dqcodesCustom.txt,
the same codes found in Tooele meet results). First digit = stroke group."""

GROUPS = {"fly": "Butterfly", "back": "Backstroke", "breast": "Breaststroke", "free": "Freestyle", "IM": "Individual Medley",
          "Relay": "Relay", "Misc": "General / starts"}

CODES = [
 {
  "code": "1A",
  "desc": "Alternating Kick",
  "group": "fly"
 },
 {
  "code": "1B",
  "desc": "Kick breaststroke type",
  "group": "fly"
 },
 {
  "code": "1C",
  "desc": "Scissors kick",
  "group": "fly"
 },
 {
  "code": "1E",
  "desc": "Non-simultaneous arms",
  "group": "fly"
 },
 {
  "code": "1F",
  "desc": "Arms underwater recovery",
  "group": "fly"
 },
 {
  "code": "1J",
  "desc": "One hand touch",
  "group": "fly"
 },
 {
  "code": "1K",
  "desc": "Not separated",
  "group": "fly"
 },
 {
  "code": "1L",
  "desc": "Non-simultaneous touch",
  "group": "fly"
 },
 {
  "code": "1M",
  "desc": "No touch",
  "group": "fly"
 },
 {
  "code": "1N",
  "desc": "Not toward the breast off wall",
  "group": "fly"
 },
 {
  "code": "1P",
  "desc": "Head did not break the surface by 15 meters",
  "group": "fly"
 },
 {
  "code": "1T",
  "desc": "Other",
  "group": "fly"
 },
 {
  "code": "1R",
  "desc": "Re-Submerged",
  "group": "fly"
 },
 {
  "code": "2A",
  "desc": "No touch at turn",
  "group": "back"
 },
 {
  "code": "2B",
  "desc": "Delay initiating arm pull",
  "group": "back"
 },
 {
  "code": "2C",
  "desc": "Delay initiating turn",
  "group": "back"
 },
 {
  "code": "2D",
  "desc": "Multiple strokes",
  "group": "back"
 },
 {
  "code": "2E",
  "desc": "Toes over lip of gutter after the start",
  "group": "back"
 },
 {
  "code": "2F",
  "desc": "Head did not break the surface by 15 meters",
  "group": "back"
 },
 {
  "code": "2G",
  "desc": "Re-Submerged",
  "group": "back"
 },
 {
  "code": "2H",
  "desc": "Not on back off wall",
  "group": "back"
 },
 {
  "code": "2L",
  "desc": "Shoulders past vertical toward breast",
  "group": "back"
 },
 {
  "code": "2T",
  "desc": "Other",
  "group": "back"
 },
 {
  "code": "3A",
  "desc": "Alternating Kick",
  "group": "breast"
 },
 {
  "code": "3B",
  "desc": "Butterfly kick",
  "group": "breast"
 },
 {
  "code": "3C",
  "desc": "Scissors kick",
  "group": "breast"
 },
 {
  "code": "3D",
  "desc": "Arms past hipline",
  "group": "breast"
 },
 {
  "code": "3F",
  "desc": "Two strokes under water",
  "group": "breast"
 },
 {
  "code": "3E",
  "desc": "Non-simultaneous arms",
  "group": "breast"
 },
 {
  "code": "3H",
  "desc": "Elbows recovered over water",
  "group": "breast"
 },
 {
  "code": "3J",
  "desc": "One hand touch",
  "group": "breast"
 },
 {
  "code": "3K",
  "desc": "Hands not separated",
  "group": "breast"
 },
 {
  "code": "3L",
  "desc": "Non-simultaneous touch",
  "group": "breast"
 },
 {
  "code": "3M",
  "desc": "No touch",
  "group": "breast"
 },
 {
  "code": "3N",
  "desc": "Not towards breast off wall",
  "group": "breast"
 },
 {
  "code": "3P",
  "desc": "Kick before pull during cycle",
  "group": "breast"
 },
 {
  "code": "3R",
  "desc": "Head not up",
  "group": "breast"
 },
 {
  "code": "3S",
  "desc": "Double pull / kicks",
  "group": "breast"
 },
 {
  "code": "3T",
  "desc": "Other",
  "group": "breast"
 },
 {
  "code": "4A",
  "desc": "No touch on turn",
  "group": "free"
 },
 {
  "code": "4B",
  "desc": "Head did not break the surface by 15 meters",
  "group": "free"
 },
 {
  "code": "4C",
  "desc": "Re-Submerged",
  "group": "free"
 },
 {
  "code": "5A",
  "desc": "Stroke Infraction",
  "group": "IM"
 },
 {
  "code": "5B",
  "desc": "Out of sequence",
  "group": "IM"
 },
 {
  "code": "5C",
  "desc": "Fourth distance swum in style of previous stroke",
  "group": "IM"
 },
 {
  "code": "6A",
  "desc": "Stroke Infraction swimmer #1",
  "group": "Relay"
 },
 {
  "code": "6B",
  "desc": "Stroke Infraction swimmer #2",
  "group": "Relay"
 },
 {
  "code": "6C",
  "desc": "Stroke Infraction swimmer #3",
  "group": "Relay"
 },
 {
  "code": "6D",
  "desc": "Stroke Infraction swimmer #4",
  "group": "Relay"
 },
 {
  "code": "6F",
  "desc": "Early take-off swimmer #2",
  "group": "Relay"
 },
 {
  "code": "6G",
  "desc": "Early take-off swimmer #3",
  "group": "Relay"
 },
 {
  "code": "6H",
  "desc": "Early take-off swimmer #4",
  "group": "Relay"
 },
 {
  "code": "6L",
  "desc": "Changed order of swimmers",
  "group": "Relay"
 },
 {
  "code": "6T",
  "desc": "Other",
  "group": "Relay"
 },
 {
  "code": "7A",
  "desc": "False start",
  "group": "Misc"
 },
 {
  "code": "7B",
  "desc": "Declared false start",
  "group": "Misc"
 },
 {
  "code": "7C",
  "desc": "Did not finish",
  "group": "Misc"
 },
 {
  "code": "7D",
  "desc": "Delay of meet",
  "group": "Misc"
 },
 {
  "code": "7T",
  "desc": "Other/Coach Assist",
  "group": "Misc"
 },
 {
  "code": "7U",
  "desc": "Walking on or springing from bottom",
  "group": "Misc"
 },
 {
  "code": "7V",
  "desc": "Standing on bottom",
  "group": "Misc"
 },
 {
  "code": "7W",
  "desc": "Pulling on lane line",
  "group": "Misc"
 },
 {
  "code": "7X",
  "desc": "Finish in wrong lane",
  "group": "Misc"
 },
 {
  "code": "7Y",
  "desc": "Unsportsmanlike conduct",
  "group": "Misc"
 },
 {
  "code": "7P",
  "desc": "Declared false start",
  "group": "Misc"
 },
 {
  "code": "7Q",
  "desc": "Did not finish",
  "group": "Misc"
 }
]

BY_CODE = {c["code"]: c for c in CODES}

# codes that mean the swimmer has no official time (time is cleared)
NO_TIME = {"7B", "7P", "7C", "7Q"}


def describe(code: str, event_stroke: str = "", relay: bool = False) -> str:
    """Description the way Meet Manager writes it in results (adds the stroke for IM and relay events)."""
    c = BY_CODE.get((code or "").strip().upper())
    if not c:
        return ""
    d = c["desc"]
    if (relay or event_stroke == "E") and c["group"] in ("fly", "back", "breast", "free"):
        d += f" - {c['group']}"
    return d
