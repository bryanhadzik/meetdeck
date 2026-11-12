"""Which NFHS Swimming & Diving rule each Meet Manager DQ code falls under (2026-27 Rules Book).

Only references and a short phrase to find the right line live here - the rule wording itself is read from the
Rules Book in this computer's rules library (it's copyrighted, so it never ships with MeetDeck).
Each code -> [(rule reference as printed, phrase that appears in that rule's line)]."""

FLY, BACK, BREAST, FREE = "8-2-3", "8-2-1", "8-2-2", "8-2-4"

CODE_RULES = {
    # butterfly (8-2-3)
    "1A": [("8-2-3d", "both legs and feet move up and down simultaneously")],
    "1B": [("8-2-3d", "both legs and feet move up and down simultaneously")],
    "1C": [("8-2-3d", "both legs and feet move up and down simultaneously")],
    "1E": [("8-2-3c", "both arms simultaneously pull backward")],
    "1F": [("8-2-3c", "both arms simultaneously pull backward")],
    "1J": [("8-2-3e", "At each turn the touch shall be made with both hands"), ("8-2-3g", "finish end with both hands separated")],
    "1K": [("8-2-3e", "At each turn the touch shall be made with both hands"), ("8-2-3g", "finish end with both hands separated")],
    "1L": [("8-2-3e", "At each turn the touch shall be made with both hands"), ("8-2-3g", "finish end with both hands separated")],
    "1M": [("8-2-3e", "At each turn the touch shall be made with both hands"), ("8-2-3g", "finish end with both hands separated")],
    "1N": [("8-2-3e", "shoulders shall be at or past the vertical")],
    "1P": [("8-2-3f", "completely submerged for a distance of not more than")],
    "1R": [("8-2-3f", "completely submerged for a distance of not more than")],
    "1T": [("8-2-3", "The Butterfly")],
    # backstroke (8-2-1)
    "2A": [("8-2-1f", "The turn requires that some part of the swimmer's body contact the end wall")],
    "2B": [("8-2-1f", "The turn requires that some part of the swimmer's body contact the end wall")],
    "2C": [("8-2-1f", "The turn requires that some part of the swimmer's body contact the end wall")],
    "2D": [("8-2-1f", "The turn requires that some part of the swimmer's body contact the end wall")],
    "2E": [("8-2-1c", "curling the toes over the lip of the gutter"), ("8-1-2", "For the backstroke start")],
    "2F": [("8-2-1e", "completely submerged during the turn and for a distance")],
    "2G": [("8-2-1e", "completely submerged during the turn and for a distance")],
    "2H": [("8-2-1f", "The turn requires that some part of the swimmer's body contact the end wall")],
    "2L": [("8-2-1b", "The body shall remain on the back")],
    "2T": [("8-2-1", "The Backstroke")],
    # breaststroke (8-2-2)
    "3A": [("8-2-2e", "The kick requires the feet be drawn up")],
    "3B": [("8-2-2e", "The kick requires the feet be drawn up"), ("8-2-2c", "a single butterfly kick is permitted")],
    "3C": [("8-2-2e", "The kick requires the feet be drawn up")],
    "3D": [("8-2-2c(1)", "hands shall not be brought back beyond the hipline")],
    "3E": [("8-2-2d", "arms shall move simultaneously")],
    "3F": [("8-2-2c", "one arm stroke beyond the hipline")],
    "3H": [("8-2-2d", "Elbows must remain under the water")],
    "3J": [("8-2-2f", "At each turn the touch shall be made with both hands"), ("8-2-2g", "finish end with both hands separated")],
    "3K": [("8-2-2f", "At each turn the touch shall be made with both hands"), ("8-2-2g", "finish end with both hands separated")],
    "3L": [("8-2-2f", "At each turn the touch shall be made with both hands"), ("8-2-2g", "finish end with both hands separated")],
    "3M": [("8-2-2f", "At each turn the touch shall be made with both hands"), ("8-2-2g", "finish end with both hands separated")],
    "3N": [("8-2-2f", "shoulders shall be at or past the vertical")],
    "3P": [("8-2-2c(2)", "one arm pull followed by one leg kick")],
    "3R": [("8-2-2c(2)", "head must break the water surface sometime during each stroke cycle")],
    "3S": [("8-2-2c(2)", "one arm pull followed by one leg kick")],
    "3T": [("8-2-2", "The Breaststroke")],
    # freestyle (8-2-4)
    "4A": [("8-2-4c", "The turn requires that some part of the swimmer's body contact the end wall")],
    "4B": [("8-2-4d", "completely submerged for a distance of not more than")],
    "4C": [("8-2-4d", "completely submerged for a distance of not more than")],
    # individual medley (8-2-5)
    "5A": [("8-2-5", "individual medley begins")],
    "5B": [("8-2-5", "individual medley begins")],
    "5C": [("8-2-5", "individual medley begins"), ("8-2-4c", "final leg of the individual medley")],
    # relays (8-3)
    "6A": [("8-3-1", "Each swimmer shall adhere"), ("8-3-2", "freestyle relay is swum")],
    "6B": [("8-3-1", "Each swimmer shall adhere"), ("8-3-2", "freestyle relay is swum")],
    "6C": [("8-3-1", "Each swimmer shall adhere"), ("8-3-2", "freestyle relay is swum")],
    "6D": [("8-3-1", "Each swimmer shall adhere"), ("8-3-2", "freestyle relay is swum")],
    "6F": [("8-3-4", "remain in contact with the starting platform")],
    "6G": [("8-3-4", "remain in contact with the starting platform")],
    "6H": [("8-3-4", "remain in contact with the starting platform")],
    "6L": [("8-3-3", "shall not change the swimming order")],
    "6T": [("8-3", "")],
    # general
    "7A": [("8-1-3", "an infraction/false start occurs"), ("8-1-3d", "leaves the mark before the starting signal")],
    "7B": [("1-4-13", "declared false start is the withdrawal")],
    "7P": [("1-4-13", "declared false start is the withdrawal")],
    "7C": [("8-1-7", "To finish the race")],
    "7Q": [("8-1-7", "To finish the race")],
    "7D": [("8-1-3a", "unnecessarily delays reporting for the start")],
    "7T": [("3-6-2", "No team personnel/competitor shall display unacceptable conduct")],
    "7U": [("3-6-2d", "contacting the bottom of the pool for the purpose of gaining an advantage")],
    "7V": [("3-6-2d", "contacting the bottom of the pool for the purpose of gaining an advantage")],
    "7W": [("3-6-2", "No team personnel/competitor shall display unacceptable conduct")],
    "7X": [("3-6-2c", "failing to swim in an assigned lane")],
    "7Y": [("3-6-1", "No participant, team personnel or coach shall display unsporting conduct")],
}

# where the NFHS book has no rule written for that exact act - the referee decides under the general conduct rule
NOTES = {
    "7W": "The Rules Book has no rule that names pulling on the lane line; it's judged under unacceptable conduct (3-6-2).",
    "7T": "No rule names coach assistance specifically; the referee judges it under 3-6-2 (or 3-6-1 if unsporting).",
}
