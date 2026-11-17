"""Draws the app icon (字 on a soft rounded tile) natively at every size into icon.ico and icons/*.png.

Each size is drawn on its own (at 4x, then downsampled) instead of shrinking one big image, so the
16-48 px versions Windows uses on the desktop, taskbar and title bars stay crisp. Small sizes get a
bolder glyph, a thinner relative border and no extra details."""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
BG, BORDER, GLYPH, BAR = (255, 236, 243), (255, 143, 179), (91, 59, 76), (255, 143, 179)  # Sakura palette


def font(size_px: int, bold: bool) -> ImageFont.FreeTypeFont:
    names = ([r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc"] if bold else
             [r"C:\Windows\Fonts\YuGothM.ttc", r"C:\Windows\Fonts\meiryo.ttc"]) + [r"C:\Windows\Fonts\msgothic.ttc"]
    for path in names:
        if os.path.exists(path):
            return ImageFont.truetype(path, size_px)
    return ImageFont.load_default()


def draw(size: int) -> Image.Image:
    k = 4  # supersampling
    S = size * k
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    small = size <= 24
    inset = 0 if size <= 20 else round(S * 0.03)
    radius = round(S * (0.22 if small else 0.24))
    border = max(k, round(S * (0.045 if small else 0.05)))  # at least 1 real pixel
    d.rounded_rectangle((inset, inset, S - 1 - inset, S - 1 - inset), radius=radius, fill=BG,
                        outline=BORDER, width=border)
    glyph_px = round(S * (0.80 if small else 0.66))
    cy = S / 2 + (S * 0.02 if small else -S * 0.03)
    d.text((S / 2, cy), "字", font=font(glyph_px, bold=True), fill=GLYPH, anchor="mm")
    if size >= 40:  # the little "progress bar" only where it can be seen
        h = round(S * 0.055)
        y = round(S * 0.80)
        d.rounded_rectangle((round(S * 0.27), y, round(S * 0.73), y + h), radius=h // 2, fill=BAR)
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(os.path.join(HERE, "icons"), exist_ok=True)
    images = [draw(s) for s in SIZES]
    for s, im in zip(SIZES, images):
        im.save(os.path.join(HERE, "icons", f"icon_{s}.png"))
    big = images[-1]
    big.save(os.path.join(HERE, "icon.ico"), sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print("icon.ico + icons/*.png written:", SIZES)


if __name__ == "__main__":
    main()
