"""
The Halloween night scene: harvest moon, twinkly sky, a street of houses with
glowing windows, a picket fence with jack-o'-lanterns, and a twisty bare tree.

Built in stages (see README). Stage 1: the still scene.

Like the Christmas plugin, characters are "pixel art" written as text: each
letter is one LED, PALETTE says which colour a letter is, a space is
see-through. Edit the letters to redraw something.

Designed for a 128x32 display (two 64x32 panels side by side).
"""

import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Colours (red, green, blue), 0-255. Black (0, 0, 0) is an LED switched off,
# so most of the screen stays black and the bright bits pop.
# ---------------------------------------------------------------------------
PALETTE = {
    # sky
    "star": (150, 150, 200),
    "moon": (255, 170, 50),
    "moon_dark": (205, 115, 25),   # craters
    "moon_glow": (45, 22, 4),      # faint halo around the moon
    # houses
    "H": (14, 14, 42),             # wall: deep navy
    "P": (40, 16, 64),             # roof: dark purple
    "p": (95, 40, 140),            # roof edge: brighter purple
    "w": (255, 185, 60),           # lit window: warm yellow
    "o": (255, 120, 20),           # lit window: orange
    "D": (70, 30, 8),              # door
    # street
    "F": (60, 50, 90),             # fence
    "grass": (15, 45, 15),         # a little green along the ground
    # jack-o'-lantern
    "O": (255, 100, 0),            # pumpkin orange
    "Y": (255, 220, 60),           # candle glow through the carved face
    "g": (40, 120, 20),            # stem
    # tree
    "tree": (62, 32, 82),          # bare tree: dark purple (black where it crosses the moon)
    # text
    "text": (255, 120, 20),
}

GROUND_Y = 28  # first row of the ground

JACK_O_LANTERN = [
    "  g  ",
    " OOO ",
    "OYOYO",
    "OOOOO",
    " YYY ",
]

# The bare, twisty tree, drawn as a list of branches:
# (start x, start y), (end x, end y), thickness. It leans in from the left and
# its branches reach across the moon, where they show as black cut-outs.
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

# Each house: left edge, width, top of the wall, roof height, window spots
# (x, y measured from the house's top-left wall corner) and the door column.
HOUSES = [
    {"x": 3, "width": 19, "wall_top": 17, "roof": 9, "door": 8,
     "windows": [(2, 2, "w"), (14, 2, "o")]},
    {"x": 28, "width": 25, "wall_top": 16, "roof": 8, "door": 11,
     "windows": [(3, 2, "w"), (11, 2, "o"), (19, 2, "w"), (3, 7, "o"), (20, 7, "w")]},
    {"x": 61, "width": 19, "wall_top": 17, "roof": 9, "door": 8,
     "windows": [(2, 2, "o"), (14, 2, "w")]},
]

# Fixed star positions (kept clear of the countdown text in the top-left
# corner and of the moon).
STARS = [(100, 2), (104, 10), (99, 7), (24, 11), (57, 10), (86, 11), (90, 14), (2, 12), (125, 20)]

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


def draw_sprite(img, picture, x, y, colour_for=None):
    """Copy a text picture onto the image with its top-left corner at (x, y)."""
    pixels = img.load()
    width, height = img.size
    for row, line in enumerate(picture):
        for col, letter in enumerate(line):
            if letter == " ":
                continue
            px, py = x + col, y + row
            if not (0 <= px < width and 0 <= py < height):
                continue
            colour = colour_for(letter, col, row) if colour_for else None
            pixels[px, py] = colour or PALETTE.get(letter, (255, 0, 255))


# ---------------------------------------------------------------------------
# Layers, drawn back to front.
# ---------------------------------------------------------------------------
def draw_sky(img):
    pixels = img.load()
    for x, y in STARS:
        pixels[x, y] = PALETTE["star"]

    cx, cy = MOON_CENTRE
    draw = ImageDraw.Draw(img)
    r = MOON_RADIUS
    draw.ellipse((cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2), fill=PALETTE["moon_glow"])
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=PALETTE["moon"])
    # A few craters.
    for dx, dy, size in ((-3, -2, 2), (2, 2, 2), (3, -4, 1), (-2, 4, 1)):
        draw.ellipse((cx + dx, cy + dy, cx + dx + size - 1, cy + dy + size - 1), fill=PALETTE["moon_dark"])


def draw_house(img, house):
    draw = ImageDraw.Draw(img)
    x, w, top, rise = house["x"], house["width"], house["wall_top"], house["roof"]
    # Wall.
    draw.rectangle((x, top, x + w - 1, GROUND_Y - 1), fill=PALETTE["H"])
    # Roof: a triangle that overhangs the wall by one pixel each side, with a
    # brighter edge so the shape reads against the black sky.
    apex = (x + (w - 1) / 2, top - rise)
    roof = [(x - 1, top - 1), apex, (x + w, top - 1)]
    draw.polygon(roof, fill=PALETTE["P"], outline=PALETTE["p"])
    # Windows (3x3) and door (3x5).
    for wx, wy, colour in house["windows"]:
        draw.rectangle((x + wx, top + wy, x + wx + 2, top + wy + 2), fill=PALETTE[colour])
    dx = x + house["door"]
    draw.rectangle((dx, GROUND_Y - 5, dx + 2, GROUND_Y - 1), fill=PALETTE["D"])


def door_gaps():
    """Columns where the fence opens up for each house's front path."""
    gaps = []
    for house in HOUSES:
        door = house["x"] + house["door"]
        gaps.append((door - 4, door + 6))
    return gaps


def draw_fence(img):
    draw = ImageDraw.Draw(img)
    width = img.size[0]
    top = GROUND_Y - 4
    gaps = door_gaps()
    fence_end = 93  # stop before the tree

    def in_gap(x):
        return any(a <= x <= b for a, b in gaps)

    for x in range(0, fence_end):
        if in_gap(x):
            continue
        # Two rails ...
        img.load()[x, top + 1] = PALETTE["F"]
        img.load()[x, top + 3] = PALETTE["F"]
        # ... and a pointed picket every 3 columns.
        if x % 3 == 0:
            draw.line((x, top, x, GROUND_Y - 1), fill=PALETTE["F"])
            if top - 1 >= 0:
                img.load()[x, top - 1] = PALETTE["F"]


def draw_porch_pumpkins(img):
    """A jack-o'-lantern on each front path, beside the door."""
    for house in HOUSES:
        door = house["x"] + house["door"]
        draw_sprite(img, JACK_O_LANTERN, door + 4, GROUND_Y - len(JACK_O_LANTERN) + 1)


def draw_tree(img):
    mask = Image.new("1", img.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    for start, end, thickness in TREE_BRANCHES:
        mask_draw.line((start, end), fill=1, width=thickness)

    m = mask.load()
    pixels = img.load()
    cx, cy = MOON_CENTRE
    width, height = img.size
    for y in range(height):
        for x in range(width):
            if m[x, y]:
                on_moon = (x - cx) ** 2 + (y - cy) ** 2 <= (MOON_RADIUS + 0.5) ** 2
                pixels[x, y] = (0, 0, 0) if on_moon else PALETTE["tree"]


def draw_ground(img):
    width, height = img.size
    draw = ImageDraw.Draw(img)
    draw.line((0, GROUND_Y, width - 1, GROUND_Y), fill=PALETTE["grass"])


def draw_countdown_text(img, text):
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"
    left, top, _, _ = TEXT_FONT.getbbox(text)
    draw.text((1 - left, 1 - top), text, font=TEXT_FONT, fill=PALETTE["text"])


def draw_scene(t, days, width=128, height=32, options=None, show_text=False):
    """Draw one frame of the scene and return it as an image."""
    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw_sky(img)
    for house in HOUSES:
        draw_house(img, house)
    draw_tree(img)
    draw_fence(img)
    draw_porch_pumpkins(img)
    draw_ground(img)
    if show_text:
        draw_countdown_text(img, f"{days} DAYS TO HALLOWEEN")
    return img
