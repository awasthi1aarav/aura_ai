"""Render the AURA demo video: 1920x1080, 30 fps, <= 30 s, smooth camera moves over crisp screenshots,
English captions, title and end cards. Silent (no voices)."""
import json
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1080, 30
F = "fonts/"
boxes = json.load(open("boxes.json"))
PAPER, INK, GOLD, GOLD_D, MUTED = (253, 252, 249), (28, 27, 25), (176, 141, 87), (138, 106, 58), (140, 133, 122)


def font(name, size):
    return ImageFont.truetype(F + name, size)


def ease(t):
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def rect_for(b, pad=0.12, src=None, aspect=W / H, anchor=0.43):
    """16:9 camera rect around box b=[x,y,w,h], padded, kept inside the source image.
    The target sits a little above centre (anchor) so the caption at the bottom doesn't cover it."""
    x, y, w, h = b
    cx, cy = x + w / 2, y + h / 2
    h = h / (2 * anchor) if anchor < 0.5 else h      # leave room below for the caption
    w2, h2 = w * (1 + pad * 2), h * (1 + pad * 2)
    if w2 / h2 < aspect:
        w2 = h2 * aspect
    else:
        h2 = w2 / aspect
    sw, sh = src
    w2, h2 = min(w2, sw), min(h2, sh)
    x0 = min(max(0, cx - w2 / 2), sw - w2)
    y0 = min(max(0, cy - h2 * anchor), sh - h2)
    return (x0, y0, w2, h2)


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def frame_from(img, r):
    x, y, w, h = r
    return img.resize((W, H), Image.LANCZOS, box=(x, y, x + w, y + h), reducing_gap=2.0)


TAG = font("PlexSans-500.ttf", 22)


def caption(im, text, alpha=1.0):
    if not text or alpha <= 0:
        return im
    f = font("PlexSans-500.ttf", 44)
    d = ImageDraw.Draw(im)
    tw = d.textlength(text, font=f)
    pw, ph = tw + 88, 92
    x0, y0 = (W - pw) / 2, H - ph - 56
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.rounded_rectangle((x0 + 4, y0 + 8, x0 + pw + 4, y0 + ph + 8), 14, fill=(0, 0, 0, int(40 * alpha)))
    ov = ov.filter(ImageFilter.GaussianBlur(10))
    od = ImageDraw.Draw(ov)
    od.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), 14, fill=INK + (int(238 * alpha),))
    od.rectangle((x0 + 30, y0 + ph - 6, x0 + 110, y0 + ph - 3), fill=GOLD + (int(255 * alpha),))
    od.text((W / 2, y0 + ph / 2 - 3), text, font=f, fill=(255, 255, 255, int(255 * alpha)), anchor="mm")
    return Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")


def demo_tag(im):
    d = ImageDraw.Draw(im)
    t = "Demo mission · simulated data"
    tw = d.textlength(t, font=TAG)
    d.rounded_rectangle((28, 26, 28 + tw + 32, 26 + 44), 22, fill=(255, 255, 255), outline=(217, 207, 186), width=2)
    d.text((44, 48), t, font=TAG, fill=GOLD_D, anchor="lm")
    return im


def title_card(t):
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    a = min(1, t / 0.6)
    col = lambda c: tuple(int(PAPER[i] + (c[i] - PAPER[i]) * a) for i in range(3))
    cx, cy = W / 2, H / 2 - 40
    d.ellipse((cx - 330, cy - 34, cx - 278, cy + 18), outline=col(GOLD), width=5)
    d.ellipse((cx - 315, cy - 19, cx - 293, cy + 3), fill=col(GOLD))
    d.text((cx + 20, cy - 8), "A U R A", font=font("Cormorant-600.ttf", 150), fill=col(INK), anchor="mm")
    d.line((cx - 120, cy + 92, cx + 120, cy + 92), fill=col(GOLD), width=3)
    d.text((cx, cy + 150), "Health monitoring for astronauts, far from Earth", font=font("PlexSans-400.ttf", 46),
           fill=col(MUTED), anchor="mm")
    return im


def end_card(t):
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    a = min(1, t / 0.4)
    col = lambda c: tuple(int(PAPER[i] + (c[i] - PAPER[i]) * a) for i in range(3))
    d.text((W / 2, H / 2 - 90), "A U R A", font=font("Cormorant-600.ttf", 120), fill=col(INK), anchor="mm")
    d.line((W / 2 - 100, H / 2 - 10, W / 2 + 100, H / 2 - 10), fill=col(GOLD), width=3)
    d.text((W / 2, H / 2 + 50), "Try it: aura-ai-bk7d.onrender.com", font=font("PlexSans-500.ttf", 46), fill=col(GOLD_D), anchor="mm")
    d.text((W / 2, H / 2 + 120), "Team Orbital Five · NASA Space Apps Challenge 2026", font=font("PlexSans-400.ttf", 34),
           fill=col(MUTED), anchor="mm")
    d.text((W / 2, H - 70), "Captions written with AI assistance · demo data is simulated", font=font("PlexSans-400.ttf", 24),
           fill=col(MUTED), anchor="mm")
    return im


def union(*bs):
    x0 = min(b[0] for b in bs); y0 = min(b[1] for b in bs)
    x1 = max(b[0] + b[2] for b in bs); y1 = max(b[1] + b[3] for b in bs)
    return [x0, y0, x1 - x0, y1 - y0]


imgs = {k: Image.open(f"s_{k}.png").convert("RGB") for k in ["dash", "alert", "earth", "body", "wellbeing", "chat"]}
size = imgs["dash"].size
full = (0, 0, size[0], size[1])

KENJI = [1232, 680, 1010, 900]                       # Dr. Kenji Mori's card in s_alert.png (2x pixels)
FORECAST = union([1232, 840, 1010, 280], [boxes["alert"][0], boxes["alert"][1], boxes["alert"][2], 760])
ANSWER = [860, 360, 1560, 480]                       # question + answer in s_chat.png

# scene: (kind, duration, image, start_rect, end_rect, caption)
S = [
    ("title", 2.6, None, None, None, None),
    ("shot", 4.4, "dash", full, rect_for([0, 140, size[0] * 0.66, 1500], 0.02, size),
     "Every astronaut's vitals and the cabin, in one place"),
    ("shot", 4.8, "alert", rect_for(union(KENJI, boxes["alert"]), 0.25, size), rect_for(FORECAST, 0.06, size),
     "AURA predicts problems before they turn critical"),
    ("shot", 3.6, "earth", rect_for(boxes["earth"], 0.35, size), rect_for(boxes["earth"], 0.12, size),
     "It knows how far help is — and how long a message takes"),
    ("shot", 4.0, "body", rect_for(boxes["body"], 0.25, size), rect_for(boxes["body"], 0.06, size),
     "Daily check-ins and an interactive body map"),
    ("shot", 3.8, "wellbeing", rect_for(boxes["wellbeing"], 0.2, size), rect_for(boxes["wellbeing"], 0.05, size),
     "It looks after the mind too: mood, stress, loneliness"),
    ("shot", 4.0, "chat", rect_for(boxes["chat"], 0.04, size), rect_for(ANSWER, 0.05, size),
     "An AI assistant explains it all in plain language"),
    ("end", 2.6, None, None, None, None),
]
total = sum(s[1] for s in S)
assert total <= 30.0, total
XF = 0.45  # crossfade seconds


def render_scene(i, t):
    kind, dur, key, r0, r1, cap = S[i]
    if kind == "title":
        return title_card(t)
    if kind == "end":
        return end_card(t)
    p = ease(min(1, max(0, t / dur)))
    im = frame_from(imgs[key], lerp(r0, r1, p))
    im = demo_tag(im)
    ca = min(1, max(0, (t - 0.25) / 0.35)) * min(1, max(0, (dur - t) / 0.3))
    return caption(im, cap, ca)


out = sys.argv[1] if len(sys.argv) > 1 else "aura-demo.mp4"
ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                       "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                       "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
starts, acc = [], 0.0
for s in S:
    starts.append(acc)
    acc += s[1]
n = int(round(total * FPS))
for fi in range(n):
    t = fi / FPS
    i = max(j for j in range(len(S)) if starts[j] <= t + 1e-9)
    im = render_scene(i, t - starts[i])
    nxt = i + 1
    if nxt < len(S) and t > starts[nxt] - XF:   # crossfade into next scene
        a = (t - (starts[nxt] - XF)) / XF
        im = Image.blend(im, render_scene(nxt, 0), ease(a))
    ff.stdin.write(im.tobytes())
ff.stdin.close()
ff.wait()
print("rendered", out, f"{total:.1f}s")
