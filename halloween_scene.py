"""
The Halloween night scene: a sunset sky glowing orange on the horizon, a big
moon with a twisty bare tree across it, and a street of three houses built
from real materials -- a brick cottage, a two-storey stone house and a wooden
Victorian with a turret -- with warm lit windows and jack-o'-lanterns.

Built in stages (see README). Stage 1: the still scene. Stage 2: the
pumpkin-head kid and the ghost walking across, and figures in a window.
Stage 3: ambient motion (stars, flicker, leaves, fog, ghost tricks).
Stage 4: surprise moments (bats, trick-or-treat, bush scare, big gust,
winking pumpkin, witch flyby), one at a time.

How the houses are drawn: each house is described by a few numbers in HOUSES
(where it is, how big, what it's made of, where the windows go). The code
first paints a "material map" -- which pixel is brick, which is glass, which is
roof -- then colours every pixel with that material's pattern (bricks with
mortar lines, stone blocks, wooden boards, roof shingles). Change the numbers
in HOUSES to move or resize anything.

Designed for a 128x32 display (two 64x32 panels side by side).
"""

import bisect
import math
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GROUND_Y = 28  # first row of the ground

# ---------------------------------------------------------------------------
# Colours (red, green, blue), 0-255. Black (0, 0, 0) is an LED switched off.
# ---------------------------------------------------------------------------
# The sky colour for each row, top to bottom: black up high, glowing orange
# down at the horizon.
SKY = [(0, 0, 0)] * 9 + [
    (8, 1, 0), (16, 3, 0), (26, 5, 0), (38, 8, 0), (52, 12, 0),
    (68, 16, 0), (84, 20, 0), (100, 24, 0), (118, 28, 0), (136, 32, 0),
    (150, 36, 0), (165, 40, 0), (178, 44, 0), (190, 48, 0),
    (200, 52, 0), (210, 56, 0), (215, 60, 0), (220, 64, 0), (225, 68, 0),
]
MOON = (255, 235, 160)
MOON_DARK = (220, 190, 110)
STAR_COLOUR = (215, 220, 240)   # soft white
TEXT = (255, 120, 10)          # pumpkin orange
TEXT_SHADOW = (90, 25, 0)      # dark ember shadow under the letters
GRASS = (20, 120, 20)

# Materials. Each pixel of a house is one of these.
NONE, BRICK, STONE, SIDING, SHINGLE, TRIM, GLASS, MULLION, DOOR, DOOR_PANEL, \
    KNOB, STEP, SHUTTER, ROOF_EDGE, LAMP, FOUNDATION, DARK = range(17)
SHADED = 100  # add to a material to draw it in shadow (under the roof edge)

TRIM_COLOUR = (205, 190, 160)        # cream window frames and roof edges
GLASS_TOP = (255, 225, 130)          # warm room light, a bit brighter up top
GLASS_COLOUR = (255, 185, 70)
MULLION_COLOUR = (60, 38, 18)        # the wooden bars across the windows
DOOR_COLOUR = (115, 60, 25)
DOOR_PANEL_COLOUR = (80, 40, 16)
SHUTTER_COLOUR = (25, 55, 35)        # dark green
STEP_COLOUR = (120, 115, 108)
FOUNDATION_COLOUR = (65, 62, 58)
ROOF_EDGE_COLOUR = (30, 28, 34)

PUMPKIN = {"O": (255, 110, 0), "Y": (255, 230, 80), "g": (40, 160, 20)}
BUSH = {"G": (25, 85, 30), "L": (45, 125, 40)}


def _hash(*values):
    """A repeatable 'random' number from some coordinates (same in, same out)."""
    h = 2166136261
    for v in values:
        h = ((h ^ (v & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    return h


# --- Material patterns. Each takes a pixel position and returns its colour. --
def brick(x, y):
    course = y // 3
    if y % 3 == 2:                                   # mortar between rows
        return (95, 82, 72)
    if (x + (course % 2) * 2) % 5 == 0:              # mortar between bricks
        return (95, 82, 72)
    which = _hash(course, (x + (course % 2) * 2) // 5) % 3
    return [(155, 55, 35), (130, 45, 30), (170, 68, 42)][which]


def stone(x, y):
    course = y // 3
    offset = (course * 3) % 6
    if y % 3 == 2 or (x + offset) % 6 == 5:          # mortar
        return (50, 47, 44)
    which = _hash(course, (x + offset) // 6) % 4
    return [(135, 128, 116), (110, 105, 98), (150, 142, 128), (96, 93, 90)][which]


def siding(x, y):
    if y % 2 == 1:                                   # shadow under each board
        return (48, 58, 64)
    return (88, 104, 112)                            # painted slate-blue boards


def shingle(x, y):
    row = y % 2
    if row == 1 and (x + (y // 2) % 2 * 2) % 4 == 0:
        return (34, 31, 38)                          # gap between shingles
    return (72, 66, 76) if row == 0 else (58, 54, 62)


FLAT = {
    TRIM: TRIM_COLOUR, MULLION: MULLION_COLOUR, DOOR: DOOR_COLOUR,
    DOOR_PANEL: DOOR_PANEL_COLOUR, KNOB: (255, 210, 80), STEP: STEP_COLOUR,
    SHUTTER: SHUTTER_COLOUR, ROOF_EDGE: ROOF_EDGE_COLOUR, LAMP: (255, 240, 170),
    FOUNDATION: FOUNDATION_COLOUR, DARK: (0, 0, 0),
}
PATTERNS = {BRICK: brick, STONE: stone, SIDING: siding, SHINGLE: shingle}


def colour_of(material, x, y, glass_top_rows):
    shaded = material >= SHADED
    if shaded:
        material -= SHADED
    if material == GLASS:
        colour = GLASS_TOP if (x, y) in glass_top_rows else GLASS_COLOUR
    elif material in PATTERNS:
        colour = PATTERNS[material](x, y)
    else:
        colour = FLAT[material]
    if shaded:
        colour = tuple(int(c * 0.5) for c in colour)
    return colour


# ---------------------------------------------------------------------------
# The houses. Numbers are pixels. "windows" are (x, y, glass width, glass
# height) measured from the left edge of the house and the top of its wall.
# ---------------------------------------------------------------------------
HOUSES = [
    {   # Brick cottage with a chimney.
        "x": 1, "width": 24, "wall_top": 19, "wall": BRICK,
        "roof": "side", "roof_rise": 6,
        "chimney": {"x": 17, "width": 3, "top": 10},
        "windows": [(3, 2, 3, 3), (18, 2, 3, 3)],
        "door": {"x": 10, "width": 4, "height": 6},
        "lamp": (15, 3),
    },
    {   # Two-storey stone house with shutters.
        "x": 29, "width": 29, "wall_top": 15, "wall": STONE,
        "roof": "side", "roof_rise": 6,
        "windows": [(3, 2, 3, 3), (23, 2, 3, 3), (3, 8, 3, 3), (23, 8, 3, 3)],
        "spooky_window": (12, 1, 5, 4),   # bigger, no crossbars: figures appear here
        "shutters": True,
        "door": {"x": 12, "width": 5, "height": 6},
        "lamp": (19, 7),
    },
    {   # Wooden Victorian with a front gable and a pointed turret.
        "x": 63, "width": 20, "wall_top": 17, "wall": SIDING,
        "roof": "front", "roof_rise": 8,
        "attic_window": True,
        "windows": [(2, 3, 3, 3), (15, 3, 3, 3)],
        "door": {"x": 8, "width": 4, "height": 6},
        "lamp": (13, 5),
        "turret": {"x": 21, "width": 7, "top": 14, "rise": 5, "window": (2, 4, 3, 5)},
    },
]

# Where the jack-o'-lanterns and bushes sit: (x, which picture)
PUMPKINS = [(16, "small"), (22, "big"), (47, "small"), (76, "small"), (89, "big")]
BUSHES = [(0, 6), (57, 5)]  # (x, width)

JACK_O_LANTERN = [
    "  g  ",
    " OOO ",
    "OYOYO",
    "OOOOO",
    " YYY ",
]
BIG_JACK_O_LANTERN = [
    "   g   ",
    " OOOOO ",
    "OOYOYOO",
    "OOOOOOO",
    "OYYYYYO",
    " OOOOO ",
]

# A bat silhouette in front of the moon.
BAT = [
    "k   k",
    "kk kk",
    " kkk ",
]

# The bare, twisty tree, drawn as a list of branches:
# (start x, start y), (end x, end y), thickness. Black against the sunset,
# and its branches cross the moon.
TREE_BRANCHES = [
    ((100, 27), (101, 20), 3),   # trunk
    ((101, 20), (103, 14), 2),
    ((99, 27), (97, 27), 1),     # roots
    ((102, 27), (105, 27), 1),
    ((103, 14), (108, 10), 1),   # big branch up and right, over the moon
    ((108, 10), (113, 7), 1),
    ((113, 7), (118, 4), 1),
    ((118, 4), (121, 1), 1),
    ((113, 7), (114, 3), 1),
    ((118, 4), (122, 5), 1),
    ((103, 14), (109, 13), 1),   # lower branch across the moon
    ((109, 13), (115, 12), 1),
    ((115, 12), (121, 10), 1),
    ((121, 10), (125, 7), 1),
    ((115, 12), (117, 15), 1),
    ((102, 16), (98, 12), 1),    # branch reaching left
    ((98, 12), (96, 8), 1),
    ((98, 12), (95, 12), 1),
]

# A few stars, only up in the dark part of the sky: beside the moon and in
# the gaps above the roofs (clear of the countdown text and the orange glow).
STARS = [(99, 2), (106, 6), (126, 3), (5, 10), (61, 10), (80, 10)]

MOON_CENTRE = (117, 9)
MOON_RADIUS = 7


# ---------------------------------------------------------------------------
# Fonts come from LEDMatrix's assets/fonts folder (see the Christmas plugin).
# ---------------------------------------------------------------------------
def _find_font_dir():
    candidates = []
    if os.environ.get("LEDMATRIX_DIR"):
        candidates.append(Path(os.environ["LEDMATRIX_DIR"]))
    candidates += list(Path(__file__).resolve().parents)
    candidates.append(Path.cwd())
    for base in candidates:
        if (base / "assets" / "fonts" / "5x7.bdf").exists():
            return base / "assets" / "fonts"
    return None


FONT_DIR = _find_font_dir()


def _font(name, size):
    if FONT_DIR is not None:
        try:
            return ImageFont.truetype(str(FONT_DIR / name), size)
        except OSError:
            pass
    return ImageFont.load_default()


TEXT_FONT = _font("5x7.bdf", 7)  # a true pixel font: crisp at 7px tall


def draw_sprite(img, picture, x, y, colours):
    """Copy a text picture onto the image with its top-left corner at (x, y)."""
    pixels = img.load()
    width, height = img.size
    for row, line in enumerate(picture):
        for col, letter in enumerate(line):
            if letter == " ":
                continue
            px, py = x + col, y + row
            if 0 <= px < width and 0 <= py < height:
                pixels[px, py] = colours.get(letter, (255, 0, 255))


# ---------------------------------------------------------------------------
# Building the material map for the houses.
# ---------------------------------------------------------------------------
def _window(draw, x, y, w, h, shutters=False, crossbars=True):
    """A window: cream frame, warm glass, a wooden cross, a sill underneath."""
    draw.rectangle((x - 1, y - 1, x + w, y + h), fill=TRIM)
    draw.rectangle((x, y, x + w - 1, y + h - 1), fill=GLASS)
    if crossbars and w >= 3:
        draw.line((x + w // 2, y, x + w // 2, y + h - 1), fill=MULLION)
    if crossbars and h >= 3:
        draw.line((x, y + h // 2, x + w - 1, y + h // 2), fill=MULLION)
    draw.line((x - 2, y + h, x + w + 1, y + h), fill=TRIM)        # sill
    if shutters:
        draw.line((x - 2, y - 1, x - 2, y + h - 1), fill=SHUTTER)
        draw.line((x + w + 1, y - 1, x + w + 1, y + h - 1), fill=SHUTTER)


def _side_roof(draw, left, right, eave_y, rise):
    """A roof seen from the side: a slanted band of shingles."""
    draw.polygon([(left, eave_y), (left + rise, eave_y - rise),
                  (right - rise, eave_y - rise), (right, eave_y)],
                 fill=SHINGLE, outline=ROOF_EDGE)
    draw.line((left, eave_y, right, eave_y), fill=TRIM)          # fascia board
    draw.line((left + rise, eave_y - rise, right - rise, eave_y - rise), fill=ROOF_EDGE)


def _front_gable(draw, x, w, top, rise, wall):
    """A pointed gable facing us: a shingled roof edge round a triangle of wall."""
    apex_x = x + (w - 1) / 2
    draw.polygon([(x - 2, top), (apex_x, top - rise - 1), (x + w + 1, top)], fill=SHINGLE)
    draw.polygon([(x + 1, top), (apex_x, top - rise + 2), (x + w - 2, top)], fill=wall)
    # Cream trim along the outside edge of the gable.
    draw.line((x - 2, top, apex_x, top - rise - 1), fill=TRIM)
    draw.line((apex_x, top - rise - 1, x + w + 1, top), fill=TRIM)


@lru_cache(maxsize=2)
def _house_layer(width, height):
    """Paint every house into a material map, then colour it in.

    Done once and remembered, because the houses never change.
    Returns (picture with see-through background, list of window glass boxes).
    """
    materials = Image.new("L", (width, height), NONE)
    draw = ImageDraw.Draw(materials)
    glass_boxes = []

    for house in HOUSES:
        x, w, top, wall = house["x"], house["width"], house["wall_top"], house["wall"]

        if "turret" in house:
            t = house["turret"]
            tx, tw = x + t["x"], t["width"]
            draw.rectangle((tx, t["top"], tx + tw - 1, GROUND_Y - 1), fill=wall)
            apex_x = tx + (tw - 1) / 2
            draw.polygon([(tx - 1, t["top"]), (apex_x, t["top"] - t["rise"] - 1),
                          (tx + tw, t["top"])], fill=SHINGLE, outline=ROOF_EDGE)
            draw.point((round(apex_x), t["top"] - t["rise"] - 2), fill=TRIM)  # finial
            wx, wy, ww, wh = t["window"]
            _window(draw, tx + wx, t["top"] + wy, ww, wh)
            glass_boxes.append((tx + wx, t["top"] + wy, ww, wh))

        if "chimney" in house:
            c = house["chimney"]
            cx = x + c["x"]
            draw.rectangle((cx, c["top"], cx + c["width"] - 1, top - 1), fill=BRICK)
            draw.line((cx - 1, c["top"], cx + c["width"], c["top"]), fill=TRIM)

        # Wall.
        draw.rectangle((x, top, x + w - 1, GROUND_Y - 1), fill=wall)

        # Roof.
        if house["roof"] == "side":
            _side_roof(draw, x - 2, x + w + 1, top - 1, house["roof_rise"])
            if "chimney" in house:   # the chimney stands in front of the roof
                c = house["chimney"]
                cx = x + c["x"]
                draw.rectangle((cx, c["top"] + 1, cx + c["width"] - 1, top - 2), fill=BRICK)
        else:
            _front_gable(draw, x, w, top, house["roof_rise"], wall)
            if house.get("attic_window"):
                ax = x + w // 2 - 1
                _window(draw, ax, top - 4, 2, 2)

        # Shadow along the top of the wall, under the roof's edge.
        draw.line((x, top, x + w - 1, top), fill=wall + SHADED)

        # Windows.
        for wx, wy, ww, wh in house["windows"]:
            _window(draw, x + wx, top + wy, ww, wh, house.get("shutters", False))
            glass_boxes.append((x + wx, top + wy, ww, wh))
        if "spooky_window" in house:
            wx, wy, ww, wh = house["spooky_window"]
            _window(draw, x + wx, top + wy, ww, wh, house.get("shutters", False),
                    crossbars=False)
            glass_boxes.append((x + wx, top + wy, ww, wh))

        # Door with a frame, panels, knob and a stone step.
        d = house["door"]
        dx, dw, dh = x + d["x"], d["width"], d["height"]
        door_top = GROUND_Y - dh
        draw.rectangle((dx - 1, door_top - 1, dx + dw, GROUND_Y - 1), fill=TRIM)
        draw.rectangle((dx, door_top, dx + dw - 1, GROUND_Y - 1), fill=DOOR)
        draw.rectangle((dx + 1, door_top + 1, dx + dw - 2, door_top + 2), fill=DOOR_PANEL)
        draw.point((dx + dw - 1, door_top + dh // 2 + 1), fill=KNOB)
        draw.line((dx - 2, GROUND_Y - 1, dx + dw + 1, GROUND_Y - 1), fill=STEP)

        # Stone foundation along the bottom of the wall (not across the door).
        for fx in range(x, x + w):
            if not (dx - 2 <= fx <= dx + dw + 1):
                draw.point((fx, GROUND_Y - 1), fill=FOUNDATION)

        # Porch lamp beside the door.
        lx, ly = house["lamp"]
        draw.point((x + lx, top + ly), fill=LAMP)

    # Now colour every pixel by its material.
    glass_top_rows = {(gx + i, gy) for gx, gy, gw, gh in glass_boxes for i in range(gw)}
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    m = materials.load()
    pixels = layer.load()
    for py in range(height):
        for px in range(width):
            material = m[px, py]
            if material != NONE:
                pixels[px, py] = colour_of(material, px, py, glass_top_rows) + (255,)
    return layer, tuple(glass_boxes)


def window_glass_boxes(width=128, height=32):
    """Where each window's glass is: (x, y, width, height). For later stages
    (a spooky face appearing in a window)."""
    return _house_layer(width, height)[1]


# ---------------------------------------------------------------------------
# The other layers.
# ---------------------------------------------------------------------------
def draw_sky(img):
    draw = ImageDraw.Draw(img)
    width, height = img.size
    for y, colour in enumerate(SKY[:height]):
        draw.line((0, y, width - 1, y), fill=colour)

    cx, cy = MOON_CENTRE
    r = MOON_RADIUS
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=MOON)
    for dx, dy, size in ((-3, -2, 2), (2, 2, 2), (3, -4, 1), (-2, 4, 1)):
        draw.ellipse((cx + dx, cy + dy, cx + dx + size - 1, cy + dy + size - 1), fill=MOON_DARK)
    draw_sprite(img, BAT, cx - 4, cy - 2, {"k": (0, 0, 0)})


def draw_tree(img):
    draw = ImageDraw.Draw(img)
    for start, end, thickness in TREE_BRANCHES:
        draw.line((start, end), fill=(0, 0, 0), width=thickness)


def draw_bushes(img):
    for x, w in BUSHES:
        draw_bush(img, x, w)


def draw_bush(img, x, w):
    draw = ImageDraw.Draw(img)
    if True:
        draw.rectangle((x, GROUND_Y - 3, x + w - 1, GROUND_Y - 1), fill=BUSH["G"])
        draw.line((x + 1, GROUND_Y - 4, x + w - 2, GROUND_Y - 4), fill=BUSH["L"])
        draw.point((x + 2, GROUND_Y - 3), fill=BUSH["L"])
        draw.point((x + w - 3, GROUND_Y - 3), fill=BUSH["L"])


WINKING_JACK_O_LANTERN = [
    "   g   ",
    " OOOOO ",
    "OOYOOOO",     # right eye shut
    "OOOOOOO",
    "OYYYYYO",
    " OOOOO ",
]
WINKING_PUMPKIN = 1   # which of PUMPKINS winks (the big one by the cottage)


def draw_pumpkins(img, t=None, wink=None):
    """Draw the jack-o'-lanterns. Given the time t, each candle flickers.
    wink is how far into a wink surprise we are (seconds), or None."""
    for i, (x, size) in enumerate(PUMPKINS):
        picture = BIG_JACK_O_LANTERN if size == "big" else JACK_O_LANTERN
        flare = 1.0
        if wink is not None and i == WINKING_PUMPKIN:
            flare = 1.25
            if 0.3 < wink < 0.7 or 1.1 < wink < 1.5:
                picture = WINKING_JACK_O_LANTERN
        colours = PUMPKIN
        if t is not None:
            # Two wobbles at odd speeds, different for every pumpkin, so the
            # flicker never looks like a repeating pattern.
            wobble = 0.5 * math.sin(t * 9.1 + i * 1.7) + 0.5 * math.sin(t * 13.7 + i * 4.1)
            glow = (0.78 + 0.22 * wobble) * flare
            colours = dict(PUMPKIN, Y=_scale(PUMPKIN["Y"], glow),
                           O=_scale(PUMPKIN["O"], 0.92 + 0.08 * wobble))
        draw_sprite(img, picture, x, GROUND_Y - len(picture) + 1, colours)


def _scale(colour, amount):
    return tuple(max(0, min(255, int(c * amount))) for c in colour)


def draw_ground(img):
    width, _ = img.size
    draw = ImageDraw.Draw(img)
    draw.line((0, GROUND_Y, width - 1, GROUND_Y), fill=GRASS)
    draw.line((0, GROUND_Y + 1, width - 1, GROUND_Y + 1), fill=tuple(c // 3 for c in GRASS))


def draw_countdown_text(img, text):
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"
    left, top, _, _ = TEXT_FONT.getbbox(text)
    draw.text((2 - left, 2 - top), text, font=TEXT_FONT, fill=TEXT_SHADOW)
    draw.text((1 - left, 1 - top), text, font=TEXT_FONT, fill=TEXT)


@lru_cache(maxsize=2)
def _background(width, height):
    """Everything that never moves, drawn once and remembered."""
    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw_sky(img)
    draw_tree(img)
    houses, _ = _house_layer(width, height)
    img.paste(houses, (0, 0), houses)
    draw_bushes(img)
    draw_pumpkins(img)
    draw_ground(img)
    return img


# ---------------------------------------------------------------------------
# Stage 2: the pumpkin-head kid and the little ghost.
# ---------------------------------------------------------------------------
KID_COLOURS = {
    "O": (235, 95, 0),      # pumpkin head
    "o": (150, 50, 0),      # pumpkin shading round the edge
    "Y": (255, 245, 120),   # candle glow through the carved face
    "g": (40, 160, 20),     # stem
    "K": (52, 52, 62),      # dark costume
    "k": (34, 34, 42),      # costume shadow
    "B": (200, 165, 105),   # paper candy bag
    "b": (150, 115, 65),    # bag shading
    "S": (90, 90, 100),     # shoes
    # candy poking out of the bag
    "r": (255, 40, 40), "y": (255, 220, 0), "c": (0, 200, 255), "p": (255, 80, 200),
}

# The candy bag, fuller after every trick-or-treat stop. Hangs from the
# kid's hand at column 7, row 9.
BAG_SIZES = [
    ["bBb",
     "BBB",
     "bBB"],
    ["ryc",
     "BBB",
     "BBB",
     "bBB"],
    ["rycp",
     "BBBB",
     "BBBB",
     "bBBB"],
    ["pryc",
     "yrcp",
     "BBBB",
     "BBBB",
     "bBBB"],
]
BAG_AT = (7, 9)

# The kid, facing right. The legs are drawn separately (KID_LEGS) so they can
# swing while walking.
KID_BODY = [
    "    gg    ",
    "  oOOOOo  ",
    " oOOOOOOo ",
    " oOYYOYYo ",
    " oOOOOOOo ",
    " oOYYYYYo ",
    "  oOYOYo  ",
    "   KKKK   ",
    "  kKKKKK  ",
    "  kKKKKK  ",
    "  kKKKK   ",
    "  kKKKK   ",
]
# Four steps of a walk: legs apart, passing, apart (other leg), passing.
KID_LEGS = [
    ["  K   K   ",
     " SS   SS  "],
    ["   K K    ",
     "   SSSS   "],
    ["  k   K   ",
     " SS   SS  "],
    ["   K k    ",
     "   SSSS   "],
]
KID_HEIGHT = len(KID_BODY) + 2

GHOST_COLOURS = {"W": (225, 235, 255), "w": (150, 160, 190), "k": (0, 0, 0)}
GHOST = [
    "  WWW  ",
    " WWWWW ",
    "WWkWkWW",
    "WWWWWWW",
    "WWWkWWw",
    "WWWWWWw",
]
SCARED_GHOST = [
    "  WWW  ",
    " WWWWW ",
    "WkWWWkW",
    "WkWWWkW",
    "WWWkWWw",
    "WWWkWWw",
]
# The wavy bottom edge of the sheet, which flutters between two shapes.
GHOST_HEMS = ["W WW Ww", "WW WW w"]

WALK_SPEED = 9.0     # pixels per second
GHOST_TRICK_EVERY = 11.0   # seconds between the ghost's tricks
LOOP_TIME = 1.6            # seconds for a loop-the-loop
ZIP_TIME = 3.0             # seconds for a zip ahead and drift back
FEET_Y = 29          # the row the kid's shoes are on


@lru_cache(maxsize=32)
def _kid_tile(step, bag_level, facing_left):
    """The kid (body, legs and bag) as a small picture, flipped if facing left.
    Returns (picture, see-through mask)."""
    width = 11
    tile = Image.new("RGB", (width, KID_HEIGHT), (0, 0, 0))
    draw_sprite(tile, KID_BODY, 0, 0, KID_COLOURS)
    draw_sprite(tile, KID_LEGS[step], 0, len(KID_BODY), KID_COLOURS)
    draw_sprite(tile, BAG_SIZES[bag_level], BAG_AT[0], BAG_AT[1], KID_COLOURS)
    mask = Image.new("1", tile.size, 0)
    for picture, (ox, oy) in ((KID_BODY, (0, 0)), (KID_LEGS[step], (0, len(KID_BODY))),
                              (BAG_SIZES[bag_level], BAG_AT)):
        for row, line in enumerate(picture):
            for col, letter in enumerate(line):
                if letter != " " and ox + col < width:
                    mask.putpixel((ox + col, oy + row), 1)
    if facing_left:
        tile, mask = tile.transpose(Image.FLIP_LEFT_RIGHT), mask.transpose(Image.FLIP_LEFT_RIGHT)
    return tile, mask


def _lerp(a, b, p):
    p = max(0.0, min(1.0, p))
    return a + (b - a) * p


def _jitter(t, amount=1):
    """A quick shake: -amount, 0 or +amount, changing many times a second."""
    return (_hash(int(t * 25)) % (2 * amount + 1)) - amount


def kid_top(t, timeline, event):
    distance = timeline.kid_distance(t)
    walking = not (event and event["kind"] == "treat")
    step = int(distance / 3) % 4 if walking else 1
    bob = 1 if walking and step in (1, 3) else 0
    return FEET_Y - KID_HEIGHT + 1 - bob, step


def draw_duo(img, t, timeline, event):
    """The kid walks left to right across the screen and comes back round;
    the ghost floats along just behind, bobbing -- unless a surprise is on."""
    kid_x = timeline.kid_x(t)
    top, step = kid_top(t, timeline, event)
    kind = event["kind"] if event else None
    into = t - event["start"] if event else 0.0

    # Where the ghost normally floats: just behind the kid, bobbing.
    home_x = kid_x - 10
    home_y = top - 1 + round(2 * math.sin(t * 2.2))
    ghost_x, ghost_y = home_x, home_y
    ghost = GHOST
    in_front = False
    facing_left = False

    if kind == "treat":
        # Turn to face the door; the ghost moves round to the other side.
        facing_left = 0.4 < into < TREAT_PAUSE - 0.4
        aside = min(into / 0.6, (TREAT_PAUSE - into) / 0.6)
        ghost_x = round(_lerp(home_x, kid_x + 12, aside))
    elif kind == "bush":
        # The ghost gets the fright of its life and hides behind the kid.
        hide_x, hide_y = kid_x + 7, top + 2
        if into < 0.35:
            pass
        elif into < 1.2:
            ghost = SCARED_GHOST
            ghost_x, ghost_y = home_x + _jitter(t), home_y - 5 + _jitter(t + 0.5)
        elif into < 2.0:
            ghost = SCARED_GHOST
            p = (into - 1.2) / 0.8
            ghost_x = round(_lerp(home_x, hide_x, p))
            ghost_y = round(_lerp(home_y - 5, hide_y, p))
        elif into < 3.6:
            ghost = SCARED_GHOST
            ghost_x, ghost_y = hide_x + _jitter(t), hide_y
        else:
            p = (into - 3.6) / (SCARE_TIME - 3.6)
            ghost_x = round(_lerp(hide_x, home_x, p))
            ghost_y = round(_lerp(hide_y, home_y, p))
    else:
        # Now and then it shows off: a loop-the-loop round the kid, or a zip
        # out in front and a lazy drift back.
        trick_number = int(t // GHOST_TRICK_EVERY)
        trick_into = t % GHOST_TRICK_EVERY
        if trick_number % 2 == 0 and trick_into < LOOP_TIME:
            angle = 2 * math.pi * trick_into / LOOP_TIME      # once round
            ghost_x = kid_x + 1 - round(11 * math.cos(angle))
            ghost_y = top + 2 - round(6 * math.sin(angle))
            in_front = math.sin(angle) < 0                    # bottom half passes in front
        elif trick_number % 2 == 1 and trick_into < ZIP_TIME:
            p = trick_into / ZIP_TIME
            ahead = p / 0.15 if p < 0.15 else 1 - (p - 0.15) / 0.85   # whoosh out, float back
            ghost_x = round(home_x + ahead * 26)

    hem = GHOST_HEMS[int(t * 4) % 2]
    if not in_front:
        draw_sprite(img, ghost + [hem], ghost_x, ghost_y, GHOST_COLOURS)
    bag_level = min(len(BAG_SIZES) - 1, timeline.treats_done(t))
    tile, mask = _kid_tile(step, bag_level, facing_left)
    img.paste(tile, (kid_x, top), mask)
    if in_front:
        draw_sprite(img, ghost + [hem], ghost_x, ghost_y, GHOST_COLOURS)


# ---------------------------------------------------------------------------
# Spooky figures that now and then rise up in the big upstairs window.
# Each is drawn as a dark shape against the lit glass.
# ---------------------------------------------------------------------------
WINDOW_FIGURE_COLOURS = {"k": (0, 0, 0), "r": (255, 20, 20), "g": (90, 255, 40)}
WINDOW_FIGURES = [
    [" kkk ",      # a shadowy figure with red eyes
     "krkrk",
     "kkkkk",
     "kkkkk"],
    ["  k  ",      # a witch
     " kkk ",
     "kkkkk",
     " kgk "],
    ["k   k",      # a black cat with green eyes
     "kkkkk",
     "kgkgk",
     "kkkkk"],
]
FIGURE_EVERY = 30.0    # seconds between appearances
FIGURE_STAYS = 4.0     # seconds each one stays


def draw_window_figure(img, t):
    width, height = img.size
    house = next(h for h in HOUSES if "spooky_window" in h)
    wx, wy, ww, wh = house["spooky_window"]
    gx, gy = house["x"] + wx, house["wall_top"] + wy

    cycle = int(t // FIGURE_EVERY)
    into = t % FIGURE_EVERY
    if into > FIGURE_STAYS:
        return
    figure = WINDOW_FIGURES[cycle % len(WINDOW_FIGURES)]
    # Rise up from the bottom of the window, wait, then sink back down.
    rise_time = 0.6
    if into < rise_time:
        shown = into / rise_time
    elif into > FIGURE_STAYS - rise_time:
        shown = (FIGURE_STAYS - into) / rise_time
    else:
        shown = 1.0
    sink = round((1 - shown) * wh)

    pixels = img.load()
    colours = WINDOW_FIGURE_COLOURS
    for row, line in enumerate(figure):
        for col, letter in enumerate(line):
            py = gy + row + sink
            if letter != " " and py < gy + wh:       # stay inside the glass
                pixels[gx + col, py] = colours[letter]


# ---------------------------------------------------------------------------
# Stage 3: ambient motion -- twinkling stars, flickering lamps, blowing
# leaves, drifting fog.
# ---------------------------------------------------------------------------
SPARKLE_EVERY = 7.0    # each star flashes a little cross about this often
SPARKLE_TIME = 0.5


def draw_twinkling_stars(img, t):
    """Stars gently brighten and dim; now and then one flashes a sparkle."""
    pixels = img.load()
    width, height = img.size
    for i, (x, y) in enumerate(STARS):
        brightness = 0.5 + 0.4 * math.sin(t * (0.9 + 0.23 * i) + i * 2.1)
        # Stars take turns to sparkle, spread out so two never flash together.
        into = (t + i * SPARKLE_EVERY / len(STARS)) % SPARKLE_EVERY
        sparkling = into < SPARKLE_TIME
        if sparkling:
            brightness = 1.0
        pixels[x, y] = _scale(STAR_COLOUR, brightness)
        if sparkling:
            arm = _scale(STAR_COLOUR, 0.45 * math.sin(math.pi * into / SPARKLE_TIME))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                px, py = x + dx, y + dy
                # Only over dark sky, never on top of the text or a roof.
                if 0 <= px < width and 0 <= py < height and sum(pixels[px, py]) < 40:
                    pixels[px, py] = arm


def draw_porch_lamps(img, t):
    """Each porch lamp flickers a little and casts a soft warm glow."""
    pixels = img.load()
    width, height = img.size
    for i, house in enumerate(HOUSES):
        lx, ly = house["lamp"]
        x, y = house["x"] + lx, house["wall_top"] + ly
        flicker = 0.85 + 0.15 * math.sin(t * 17.0 + i * 2.3) * math.sin(t * 5.3 + i)
        pixels[x, y] = _scale((255, 240, 170), flicker)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            px, py = x + dx, y + dy
            if 0 <= px < width and 0 <= py < height:
                r, g, b = pixels[px, py]
                pixels[px, py] = (min(255, r + int(70 * flicker)), min(255, g + int(45 * flicker)),
                                  min(255, b + int(10 * flicker)))


# The wind. It goes calm -> gusty -> calm about every 14 seconds. gust(t) is
# how strong it is right now (0 to 1); wind_travel(t) is how far it has pushed
# a leaf so far (the running total of gust). Both are worked out from the
# time, so nothing needs remembering between frames.
GUST_PERIOD = 14.0
CALM_SPEED = 3.0       # pixels per second when it's calm
GUST_SPEED = 38.0      # extra pixels per second at the height of a gust


def gust(t):
    return ((1 - math.cos(2 * math.pi * t / GUST_PERIOD)) / 2) ** 2


def wind_travel(t):
    w = 2 * math.pi / GUST_PERIOD
    # The total of gust() from 0 to t, written out by hand.
    return 3 * t / 8 - math.sin(w * t) / (2 * w) + math.sin(2 * w * t) / (16 * w)


LEAF_COLOURS = [(230, 90, 0), (200, 40, 10), (240, 170, 20), (130, 70, 20), (255, 120, 0)]
_LEAVES = [
    # (start x, resting height, how high a gust lifts it, flutter speed, colour)
    (7, 27, 9, 5.0, 0), (31, 25, 13, 6.3, 1), (52, 28, 7, 4.4, 2), (70, 26, 11, 7.1, 3),
    (88, 24, 15, 5.6, 4), (104, 27, 8, 6.8, 0), (119, 25, 12, 4.9, 2), (15, 22, 10, 6.0, 1),
    (62, 21, 14, 5.2, 4), (97, 23, 9, 7.6, 3),
]


def draw_leaves(img, t):
    pixels = img.load()
    width, height = img.size
    lap = width + 10
    strength = gust(t)
    for i, (start, rest_y, lift, flutter, colour_index) in enumerate(_LEAVES):
        lag = i * 0.15                                    # leaves don't all move at once
        travel = CALM_SPEED * t + GUST_SPEED * wind_travel(t - lag)
        x = int((start + travel) % lap) - 5
        y = round(rest_y - lift * gust(t - lag) + 1.5 * math.sin(t * flutter + i))
        colour = LEAF_COLOURS[colour_index]
        # Tumbling: the leaf flips between a dot and a little 2-pixel shape.
        spin = int(t * flutter * (0.5 + strength)) % 3
        dots = [(0, 0)] if spin == 0 else [(0, 0), (1, 0)] if spin == 1 else [(0, 0), (0, 1)]
        for dx, dy in dots:
            px, py = x + dx, y + dy
            if 0 <= px < width and 0 <= py < height:
                pixels[px, py] = colour


FOG_COLOUR = (150, 150, 175)
FOG_TOP = 24          # fog reaches up to this row at its thickest
FOG_SPEED = 2.5       # pixels per second, drifting right


def draw_fog(img, t):
    """Low patchy fog along the bottom, see-through, drifting slowly."""
    pixels = img.load()
    width, height = img.size
    for x in range(width):
        drift = x - FOG_SPEED * t
        # Wavy thickness made of three slow waves, so the patches look natural.
        density = (0.5 + 0.25 * math.sin(drift * 0.09) + 0.15 * math.sin(drift * 0.23 + 1.0)
                   + 0.1 * math.sin(drift * 0.041 + 2.0 + t * 0.2))
        depth = height - FOG_TOP
        for y in range(FOG_TOP, height):
            # Thicker near the ground, fading out as it rises.
            amount = density * ((y - FOG_TOP + 1) / depth) * 0.45
            if amount <= 0.02:
                continue
            r, g, b = pixels[x, y]
            fr, fg, fb = FOG_COLOUR
            pixels[x, y] = (int(r + (fr - r) * amount), int(g + (fg - g) * amount),
                            int(b + (fb - b) * amount))


# ---------------------------------------------------------------------------
# Stage 4: surprise moments. One at a time, every 20-40 seconds.
#
# The night is split into slots (30 seconds by default). Each slot gets one
# surprise, starting somewhere 8-18 seconds into it, so the gap between
# surprises varies. The window figures use the first few seconds of each 30,
# so they never clash.
#
# The trick-or-treat stops make the kid pause, which changes where the kid is
# for the rest of the night, so the Timeline keeps track of every pause.
# ---------------------------------------------------------------------------
SURPRISES = ["bats", "treat", "bush", "gust", "wink", "witch"]
TREAT_PAUSE = 5.5      # seconds the kid stands at a door
CANDY_IN_BAG = 2.6     # seconds into a stop when the last candy lands
SCARE_TIME = 4.5
DURATIONS = {"bats": 4.5, "treat": TREAT_PAUSE, "bush": SCARE_TIME, "gust": 4.5,
             "wink": 2.0, "witch": 4.0}
MAX_WAIT = 8.0         # how far ahead a door or the bush may be, in seconds of walking

# Where the kid stops for each door: just to the right of it, then turns round.
DOOR_STOPS = [h["x"] + h["door"]["x"] + h["door"]["width"] + 1 for h in HOUSES]
SCARE_BUSH = BUSHES[1]
# The ghost reaches the bush when the kid is this far along.
SCARE_AT_KID_X = SCARE_BUSH[0] + 9


def kind_id(kind):
    return SURPRISES.index(kind)


class Timeline:
    """Plans the surprises slot by slot and keeps track of the kid's pauses."""

    def __init__(self, every, width, speed=WALK_SPEED):
        self.every = every
        self.speed = speed
        self.lap = width + 40
        self.events = []          # one per slot (or None)
        self.pause_starts = []    # start time of every trick-or-treat stop, in order
        self.last_used = {}       # surprise -> slot it last happened in

    # -- where the kid is ---------------------------------------------------
    def paused_before(self, t):
        done = bisect.bisect_right(self.pause_starts, t)
        total = done * TREAT_PAUSE
        if done:
            overrun = self.pause_starts[done - 1] + TREAT_PAUSE - t
            if overrun > 0:                 # in the middle of a stop right now
                total -= overrun
        return total

    def kid_distance(self, t):
        self._plan_until(t)
        return self.speed * (t - self.paused_before(t))

    def _kid_x_exact(self, t):
        return (self.speed * (t - self.paused_before(t))) % self.lap - 20

    def kid_x(self, t):
        self._plan_until(t)
        return int(self._kid_x_exact(t))

    def treats_done(self, t):
        self._plan_until(t)
        return bisect.bisect_right(self.pause_starts, t - CANDY_IN_BAG)

    # -- the surprises ------------------------------------------------------
    def current(self, t):
        """The surprise happening at time t, or None."""
        self._plan_until(t)
        slot = int(t // self.every)
        for k in (slot, slot - 1):
            event = self.events[k] if 0 <= k < len(self.events) else None
            if event and event["start"] <= t < event["end"]:
                return event
        return None

    def _plan_until(self, t):
        while len(self.events) * self.every <= t + self.every:
            self._plan(len(self.events))

    def _plan(self, k):
        start = k * self.every + 8 + _hash(k, 1) % 11
        # Try the surprise that has gone longest without happening first, so
        # they all take turns (ties broken by a shuffle). Skip one that needs
        # the kid somewhere they can't get to in time.
        order = sorted(SURPRISES, key=lambda kind: (self.last_used.get(kind, -1), _hash(k, kind_id(kind))))
        for kind in order:
            begin = start
            if kind in ("treat", "bush"):
                kx = self._kid_x_exact(start)
                targets = DOOR_STOPS if kind == "treat" else [SCARE_AT_KID_X]
                ahead = [x for x in targets if x > kx + 0.5]
                if not ahead or (ahead[0] - kx) / self.speed > MAX_WAIT:
                    continue
                begin = start + (ahead[0] - kx) / self.speed
            event = {"kind": kind, "start": begin, "end": begin + DURATIONS[kind]}
            if kind == "treat":
                event["house"] = DOOR_STOPS.index(ahead[0])
                self.pause_starts.append(begin)
            self.events.append(event)
            self.last_used[kind] = k
            return
        self.events.append(None)


_timelines = {}


def get_timeline(every, width):
    key = (every, width)
    if key not in _timelines:
        _timelines[key] = Timeline(every, width)
    return _timelines[key]


# -- Trick-or-treat: the door opens and candy flies into the bag. -------------
CANDY_COLOURS = [(255, 40, 40), (255, 220, 0), (0, 200, 255), (255, 80, 200)]


def draw_open_door(img, house, into):
    if not 0.8 < into < 3.4:
        return
    d = house["door"]
    dx, dw, dh = house["x"] + d["x"], d["width"], d["height"]
    draw = ImageDraw.Draw(img)
    draw.rectangle((dx, GROUND_Y - dh, dx + dw - 1, GROUND_Y - 1), fill=(255, 195, 95))
    draw.line((dx, GROUND_Y - dh, dx, GROUND_Y - 1), fill=DOOR_PANEL_COLOUR)  # door swung open
    if 1.0 < into < 2.8:                       # a hand holding out the candy
        draw.point((dx + dw - 1, GROUND_Y - dh + 3), fill=(230, 175, 135))


def draw_candy(img, house, into, kid_x, top):
    d = house["door"]
    from_x = house["x"] + d["x"] + d["width"] - 1
    from_y = GROUND_Y - d["height"] + 3
    to_x, to_y = kid_x + 2, top + BAG_AT[1]
    pixels = img.load()
    for i, launch in enumerate((1.2, 1.6, 2.0)):
        p = (into - launch) / 0.5
        if 0 <= p <= 1:
            x = round(_lerp(from_x, to_x, p))
            y = round(_lerp(from_y, to_y, p) - 4 * math.sin(math.pi * p))   # a little arc
            pixels[x, y] = CANDY_COLOURS[i % len(CANDY_COLOURS)]


# -- Bush scare: a little monster pops up from behind the bush. ---------------
MONSTER = [
    "G   G",
    "GGGGG",
    "GyGyG",
    "GGGGG",
    "GwGwG",
]
MONSTER_COLOURS = {"G": (60, 200, 40), "y": (255, 240, 0), "w": (240, 240, 240)}


def draw_bush_monster(img, into):
    bx, bw = SCARE_BUSH
    if into < 0.35:
        shown = into / 0.35
    elif into < 1.8:
        shown = 1.0
    elif into < 2.2:
        shown = 1 - (into - 1.8) / 0.4
    else:
        return
    y = GROUND_Y - 3 - round(shown * len(MONSTER))
    draw_sprite(img, MONSTER, bx, y, MONSTER_COLOURS)
    draw_bush(img, bx, bw)        # the bush in front hides the monster's body


# -- Bats sweep across the sky. ------------------------------------------------
BAT_FRAMES = [
    ["kk kk",
     " kkk "],
    [" kkk ",
     "kk kk"],
]


def draw_bats(img, into, count=7):
    width, _ = img.size
    for i in range(count):
        x = round(width + 4 - 42 * into + (_hash(i, 3) % 30))
        y = 11 + (i * 3) % 8 + round(2 * math.sin(into * 5 + i))
        frame = BAT_FRAMES[(int(into * 10) + i) % 2]
        draw_sprite(img, frame, x, y, {"k": (0, 0, 0)})


# -- A witch on a broomstick flies across the moon. ----------------------------
WITCH = [
    "    k    ",
    "   kk    ",
    "  kkkk   ",
    "   kkk   ",
    "  kkkk   ",
    "kkkkkkkkk",
    "k k  k   ",
]


def draw_witch(img, into):
    x = round(86 + 12 * into)
    y = 5 + round(1.5 * math.sin(into * 3))
    pixels = img.load()
    width, height = img.size
    cx, cy = MOON_CENTRE
    for row, line in enumerate(WITCH):
        for col, letter in enumerate(line):
            px, py = x + col, y + row
            if letter == " " or not (0 <= px < width and 0 <= py < height):
                continue
            on_moon = (px - cx) ** 2 + (py - cy) ** 2 <= MOON_RADIUS ** 2
            bright_behind = sum(pixels[px, py]) > 60
            # Black against the moon or sunset; a faint grey against black sky.
            pixels[px, py] = (0, 0, 0) if on_moon or bright_behind else (55, 55, 60)


# -- A big gust: a wave of leaves across the whole screen. ---------------------
def draw_gust_wave(img, into, count=34):
    pixels = img.load()
    width, height = img.size
    for i in range(count):
        x = round(-8 + 55 * into - (_hash(i, 4) % 45))
        y = 8 + _hash(i, 5) % 21 + round(2 * math.sin(into * 6 + i))
        colour = LEAF_COLOURS[i % len(LEAF_COLOURS)]
        spin = (int(into * 12) + i) % 3
        dots = [(0, 0)] if spin == 0 else [(0, 0), (1, 0)] if spin == 1 else [(0, 0), (0, 1)]
        for dx, dy in dots:
            px, py = x + dx, y + dy
            if 0 <= px < width and 0 <= py < height:
                pixels[px, py] = colour


def draw_scene(t, days, width=128, height=32, options=None, show_text=False):
    """Draw one frame of the scene and return it as an image."""
    options = options or {}
    timeline = get_timeline(float(options.get("surprise_every", 30)), width)
    event = timeline.current(t)
    kind = event["kind"] if event else None
    into = t - event["start"] if event else 0.0

    img = _background(width, height).copy()
    draw_twinkling_stars(img, t)
    if kind == "witch":
        draw_witch(img, into)
    draw_porch_lamps(img, t)
    draw_pumpkins(img, t, wink=into if kind == "wink" else None)
    draw_window_figure(img, t)
    if kind == "treat":
        draw_open_door(img, HOUSES[event["house"]], into)
    if kind == "bush":
        draw_bush_monster(img, into)
    draw_duo(img, t, timeline, event)
    if kind == "treat":
        top, _ = kid_top(t, timeline, event)
        draw_candy(img, HOUSES[event["house"]], into, timeline.kid_x(t), top)
    draw_fog(img, t)
    draw_leaves(img, t)
    if kind == "gust":
        draw_gust_wave(img, into)
    if kind == "bats":
        draw_bats(img, into)
    if show_text:
        draw_countdown_text(img, f"{days} DAYS TO HALLOWEEN")
    return img
