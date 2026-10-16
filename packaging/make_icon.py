"""Draws Hop's app icon: two screens with an amber arc hopping from one to the other.

Writes static/icon.png (1024, macOS-style tile with margin and shadow), static/icon-180.png
(full-bleed, iOS rounds it), static/icon-192.png, static/icon-512.png and static/icon.ico.
Run: python packaging/make_icon.py   (needs Pillow)
"""
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
S = 4  # supersampling


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(len(a)))


def vertical_gradient(size, top, bottom):
    g = Image.new("RGBA", (1, 256))
    for y in range(256):
        g.putpixel((0, y), lerp(top, bottom, y / 255.0))
    return g.resize(size, Image.BICUBIC)


def artwork(px, full_bleed=False):
    """The icon at px×px. full_bleed: square tile edge to edge (iOS / small sizes)."""
    W = px * S
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    if full_bleed:
        x0, y0, side = 0, 0, W
        radius = 0
    else:  # macOS Big Sur grid: 824/1024 tile, centred
        side = int(W * 824 / 1024)
        x0 = y0 = (W - side) // 2
        radius = int(side * 0.2237)
        shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle([x0, y0 + side * 0.02, x0 + side, y0 + side * 1.02],
                                                  radius, fill=(0, 0, 0, 110))
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(side * 0.025)))

    # Tile: charcoal with a faint warm glow rising from the bottom (Quiet AI's palette)
    tile = vertical_gradient((side, side), (30, 30, 34, 255), (12, 12, 14, 255))
    glow = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([side * 0.15, side * 0.70, side * 0.85, side * 1.30], fill=(246, 156, 52, 34))
    tile = Image.alpha_composite(tile, glow.filter(ImageFilter.GaussianBlur(side * 0.12)))
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, side - 1, side - 1], radius, fill=255)
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    layer.paste(tile, (x0, y0), mask)
    img = Image.alpha_composite(img, layer)
    if not full_bleed:  # subtle top highlight edge
        edge = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        ImageDraw.Draw(edge).rounded_rectangle([x0, y0, x0 + side - 1, y0 + side - 1], radius,
                                               outline=(255, 255, 255, 34), width=max(2, side // 260))
        img = Image.alpha_composite(img, edge)

    d = ImageDraw.Draw(img)
    u = side / 100.0  # tile units

    def X(v):
        return x0 + v * u

    def Y(v):
        return y0 + v * u

    # Two screens
    lw = 3.2 * u
    for cx in (28, 72):
        d.rounded_rectangle([X(cx - 17), Y(56), X(cx + 17), Y(80)], 4.2 * u,
                            outline=(225, 225, 230, 235), width=int(lw))
        d.rounded_rectangle([X(cx - 7), Y(86) - lw / 2, X(cx + 7), Y(86) + lw / 2], lw / 2, fill=(225, 225, 230, 150))

    # The hop: an arc from the left screen to the right one, amber gradient
    arc = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arc)
    cx, cy, r = X(50), Y(54), 22 * u
    ry = r * 0.92
    ad.arc([cx - r, cy - ry, cx + r, cy + ry], 180, 360, fill=(255, 255, 255, 255), width=int(5.2 * u))
    for px_ in (cx - r + 2.6 * u, cx + r - 2.6 * u):  # rounded ends resting on the screens
        e = 2.6 * u
        ad.ellipse([px_ - e, cy - e, px_ + e, cy + e], fill=(255, 255, 255, 255))
    grad = vertical_gradient((W, W), (255, 208, 122, 255), (242, 132, 34, 255))
    amber = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    amber.paste(grad, (0, 0), arc.split()[3])
    # fade the arc's start so it reads as motion from left to right
    fade = Image.new("L", (W, W), 0)
    fd = ImageDraw.Draw(fade)
    for i in range(256):
        x = X(28) + (X(72) - X(28)) * i / 255.0
        fd.rectangle([x, 0, x + (X(72) - X(28)) / 255.0 + 1, W], fill=int(110 + 145 * (i / 255.0)))
    fd.rectangle([0, 0, X(28), W], fill=110)
    fd.rectangle([X(72), 0, W, W], fill=255)
    amber.putalpha(ImageChops.multiply(amber.split()[3], fade))
    img = Image.alpha_composite(img, amber)

    # The ball at the top of the hop, with a soft glow
    bx, by, br = X(50), Y(54) - r * 0.92, 7.2 * u
    halo = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse([bx - br * 2.2, by - br * 2.2, bx + br * 2.2, by + br * 2.2], fill=(255, 190, 90, 90))
    img = Image.alpha_composite(img, halo.filter(ImageFilter.GaussianBlur(br * 0.9)))
    ball = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    bm = Image.new("L", (W, W), 0)
    ImageDraw.Draw(bm).ellipse([bx - br, by - br, bx + br, by + br], fill=255)
    ball.paste(vertical_gradient((W, W), (255, 224, 160, 255), (246, 140, 40, 255)), (0, 0), bm)
    img = Image.alpha_composite(img, ball)
    return img.resize((px, px), Image.LANCZOS)


def main():
    artwork(1024).save(os.path.join(STATIC, "icon.png"))
    artwork(180, full_bleed=True).convert("RGB").save(os.path.join(STATIC, "icon-180.png"))
    artwork(192).save(os.path.join(STATIC, "icon-192.png"))
    artwork(512).save(os.path.join(STATIC, "icon-512.png"))
    big = artwork(256)
    big.save(os.path.join(STATIC, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Icons written to", STATIC)


if __name__ == "__main__":
    main()
