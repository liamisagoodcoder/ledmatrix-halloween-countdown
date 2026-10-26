"""
Preview the Halloween scene on your computer, no LED panel needed.

Run it from your LEDMatrix folder (that's where the fonts live), or set
LEDMATRIX_DIR to that folder:

    python3 ~/ledmatrix-halloween-countdown/preview.py             # 6 days to go
    python3 ~/ledmatrix-halloween-countdown/preview.py --days 0    # Halloween

Writes preview/still.png and preview/animation.gif next to this file. Each
LED is drawn as a round dot so it looks close to the real panel.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

import halloween_scene
from halloween_scene import draw_scene

HERE = Path(__file__).resolve().parent


def led_look(frame, scale=6):
    """Blow the frame up and turn each pixel into a round LED dot."""
    big = frame.resize((frame.width * scale, frame.height * scale), Image.NEAREST)
    dot = Image.new("L", (scale, scale), 0)
    ImageDraw.Draw(dot).ellipse((0, 0, scale - 2, scale - 2), fill=255)
    mask = Image.new("L", big.size, 0)
    for x in range(0, big.width, scale):
        for y in range(0, big.height, scale):
            mask.paste(dot, (x, y))
    out = Image.new("RGB", big.size, (12, 12, 14))
    out.paste(big, (0, 0), mask)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=6)
    parser.add_argument("--seconds", type=float, default=19.0)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--out", type=Path, default=HERE / "preview")
    args = parser.parse_args()

    if halloween_scene.FONT_DIR is None:
        print("Warning: LEDMatrix fonts not found -- run this from your LEDMatrix "
              "folder or set LEDMATRIX_DIR. Using a fallback font.")

    args.out.mkdir(exist_ok=True)
    options = {}
    frames = [
        led_look(draw_scene(i / args.fps, args.days, options=options, show_text=True))
        for i in range(int(args.seconds * args.fps))
    ]
    led_look(draw_scene(4.2, args.days, options=options)).save(args.out / "still.png")
    led_look(draw_scene(4.2, args.days, options=options, show_text=True)).save(
        args.out / "still_with_text.png")
    save_gif(frames, args.out / "animation.gif", args.fps)

    # Highlights: a few seconds of each of the first six surprises, back to
    # back, so you don't have to wait minutes between them.
    timeline = halloween_scene.get_timeline(30.0, 128)
    timeline.current(200)
    highlights = []
    for event in [e for e in timeline.events if e][:6]:
        start = event["start"] - 0.8
        length = event["end"] - event["start"] + 1.6
        highlights += [
            led_look(draw_scene(start + i / args.fps, args.days, options=options, show_text=True))
            for i in range(int(length * args.fps))
        ]
    save_gif(highlights, args.out / "surprises.gif", args.fps)
    print(f"Wrote {args.out / 'animation.gif'} and {args.out / 'surprises.gif'}")


def save_gif(frames, path, fps):
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=1000 // fps, loop=0)


if __name__ == "__main__":
    main()
