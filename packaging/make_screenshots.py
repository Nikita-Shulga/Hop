"""Composes the README images (docs/images/hero-*.png) from raw screenshots of the app window and the
phone page (docs/images/raw-*.jpg): rounded window and phone frames with soft shadows."""
import os
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "images")


def rounded(img, r):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], r, fill=255)
    out = img.convert("RGBA"); out.putalpha(m)
    return out


def shadow(canvas, box, r, strength, blur):
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(sh).rounded_rectangle([x0, y0 + blur // 3, x1, y1 + blur // 3], r, fill=(0, 0, 0, strength))
    return Image.alpha_composite(canvas, sh.filter(ImageFilter.GaussianBlur(blur)))


def compose(mode):
    dark = mode == "dark"
    W, H = 1600, 1000
    top, bot = ((20, 20, 23), (10, 10, 11)) if dark else ((246, 246, 248), (235, 235, 239))
    bg = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([200, 650, 1400, 1400], fill=(246, 156, 52, 46 if dark else 30))
    bg = Image.alpha_composite(bg, glow.filter(ImageFilter.GaussianBlur(160)))

    host = Image.open(os.path.join(HERE, "raw-host-%s.jpg" % mode))
    host = host.resize((int(host.width * 900 / host.height), 900), Image.LANCZOS)
    hx, hy = 250, 50
    bg = shadow(bg, (hx, hy, hx + host.width, hy + host.height), 26, 150 if dark else 60, 40)
    bg.alpha_composite(rounded(host, 26), (hx, hy))
    edge = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle([hx, hy, hx + host.width - 1, hy + host.height - 1], 26,
                                           outline=(255, 255, 255, 30) if dark else (0, 0, 0, 22), width=2)
    bg = Image.alpha_composite(bg, edge)

    phone = Image.open(os.path.join(HERE, "raw-phone-%s.jpg" % mode))
    phone = phone.crop((0, 110, phone.width, min(phone.height, 1530)))  # drop the empty top/bottom
    pw, ph = 390, int(390 * phone.height / phone.width)
    phone = phone.resize((pw, ph), Image.LANCZOS)
    bezel = 14
    frame = Image.new("RGBA", (pw + 2 * bezel, ph + 2 * bezel), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rounded_rectangle([0, 0, frame.width - 1, frame.height - 1], 62,
                                            fill=(28, 28, 31) if dark else (24, 24, 27))
    frame.alpha_composite(rounded(phone, 50), (bezel, bezel))
    px, py = 860, (H - (ph + 2 * bezel)) // 2 + 20
    bg = shadow(bg, (px, py, px + frame.width, py + frame.height), 62, 170 if dark else 80, 46)
    bg.alpha_composite(frame, (px, py))
    if py + frame.height > H:
        pass
    bg = bg.crop((0, 0, W, H))
    bg.convert("RGB").save(os.path.join(HERE, "hero-%s.png" % mode), optimize=True)
    print("wrote hero-%s.png" % mode)


if __name__ == "__main__":
    compose("dark"); compose("light")
