"""Generate the fictional demo drawings (run once with a Pillow interpreter).

Outputs app/demo/*.png: simple dimensioned sketches, clearly fictional.
Not part of the running app.
"""

import os

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise SystemExit("Pillow is required to regenerate demos: %s" % exc)

HERE = os.path.dirname(os.path.abspath(__file__))
NAVY = (18, 63, 99)
RED = (160, 30, 30)
GREY = (110, 120, 130)


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _sheet(title):
    image = Image.new("RGB", (900, 640), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 18), title, fill=NAVY, font=_font(30))
    draw.text((30, 58), "FICTIONAL DEMO - NOT A REAL CUSTOMER DRAWING", fill=GREY,
              font=_font(20))
    return image, draw


def panel():
    image, draw = _sheet("GRP COVER PANEL")
    draw.rectangle([120, 150, 780, 510], outline=NAVY, width=4)
    draw.rectangle([170, 200, 730, 460], outline=NAVY, width=2)
    draw.line([120, 540, 780, 540], fill=RED, width=2)
    draw.text((400, 545), "1200", fill=RED, font=_font(26))
    draw.line([810, 150, 810, 510], fill=RED, width=2)
    draw.text((815, 310), "800", fill=RED, font=_font(26))
    draw.text((140, 165), "flange 50 all round", fill=RED, font=_font(24))
    draw.text((330, 300), "thk 5", fill=RED, font=_font(30))
    image.save(os.path.join(HERE, "panel_complete.png"))


def cylinder():
    image, draw = _sheet("GRP WATER TANK")
    draw.rectangle([300, 170, 600, 520], outline=NAVY, width=4)
    draw.ellipse([300, 120, 600, 200], outline=NAVY, width=4)
    draw.arc([300, 470, 600, 550], start=0, end=180, fill=NAVY, width=3)
    draw.line([300, 550, 600, 550], fill=RED, width=2)
    draw.text((380, 555), "DIA ~1.2 m?", fill=RED, font=_font(26))
    draw.line([650, 170, 650, 520], fill=RED, width=2)
    draw.text((655, 320), "H 1.5 m?", fill=RED, font=_font(26))
    draw.text((330, 300), "thk ?", fill=RED, font=_font(30))
    draw.text((330, 340), "open top?", fill=RED, font=_font(24))
    image.save(os.path.join(HERE, "cylinder_ambiguous.png"))


def reducer():
    image, draw = _sheet("DUCT REDUCER")
    draw.polygon([(250, 480), (650, 480), (560, 200), (340, 200)], outline=NAVY, width=4)
    draw.ellipse([250, 450, 650, 510], outline=NAVY, width=3)
    draw.ellipse([340, 175, 560, 225], outline=NAVY, width=3)
    draw.text((400, 520), "850 mm", fill=RED, font=_font(26))
    draw.text((580, 190), "60 cm", fill=RED, font=_font(26))
    draw.line([690, 200, 690, 480], fill=RED, width=2)
    draw.text((695, 320), "H 45 cm", fill=RED, font=_font(24))
    draw.text((420, 330), "thk ?", fill=RED, font=_font(30))
    draw.text((330, 580), "flange both ends?", fill=RED, font=_font(24))
    image.save(os.path.join(HERE, "reducer_conflict.png"))


if __name__ == "__main__":
    panel()
    cylinder()
    reducer()
    print("demo drawings written to", HERE)