#!/usr/bin/env python3
"""Build the avatar assets for the board from the AI-generated sheets in design/avatar/.

    uv run --no-project --with pillow --with numpy --with scipy --with opencv-python-headless python tools/build_avatar.py

Writes firmware/avatar/*.raw (RGB565 big-endian, what the panel wants; ordered dither hides the banding of smooth skin):
  full screen    240x320   neutra (the only full image: the head never changes, so it never jumps)
  eye pieces     160x84    e_<pose>, e_meio, e_pisca   (pasted at EYES, feathered into the neutral face)
  mouth pieces    96x56    m_fechada m_a m_o m_e m_u m_pensando + one per emotion (pasted at MOUTH)
The board composes: neutral face + eye piece + mouth piece. Every pose, emotion and speech frame is built this way.
Each frame is first registered to the neutral one (rigid parts only), otherwise pieces cut from it would sit a few
pixels off and the face would look misaligned.
"""
import os
import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SPRITE_SHEET = os.path.join(ROOT, "design/avatar/folha_sprite.jpg")    # 12 frames, 3 cols x 4 rows, one generation
OLD_SHEET = os.path.join(ROOT, "design/avatar/folha_original.jpg")     # first sheet (16 frames, labels): only for "confusa"
OUT = os.path.join(ROOT, "firmware/avatar")
# frame order on the sprite sheet (row-major, 1-based): there is no "confusa" frame (12 frames instead of 13)
SPRITE = {"pisca": 1, "meio": 2, "a": 3, "o": 4, "e": 5, "u": 6, "feliz": 7, "triste": 8, "surpresa": 9, "curiosa": 10,
          "pensando": 11, "neutra": 12}
OLD_CONFUSA = 15            # tile of the old sheet, used until a sprite-sheet "confusa" exists
HAIR_TOP = (76, 90)         # screen rows: above this the hair comes from the neutral frame (frames touching the cell
                            # edge have the crown cut flat)

# grids found from the all-green bands between the cells
OLD_GRID = ([(16, 216), (238, 440), (461, 663), (682, 884)], [(26, 303), (326, 600), (619, 898), (911, 1200)], 30)
SPRITE_GRID = ([(0, 299), (299, 597), (597, 896)], [(0, 300), (300, 600), (600, 900), (900, 1200)], 0)   # frames touch

OW, OH = 224, 270                  # aligned tile
REF_W, REF_C = 170.0, (112.0, 126.0)   # glasses width / centre that every tile is moved to
BG = (10, 12, 20)
MOUTH = (72, 184, 168, 240)        # x0, y0, x1, y1 (multiples of 4: the dither pattern stays aligned)
REG_BELOW = 168                    # tile rows from here down are ignored when registering frames
EYES = (40, 88, 200, 172)          # starts above the brows of every expression
FEATHER = 8
DIFF_THR = 60                      # summed RGB difference that counts as "this pixel changed"
MOUTH_ZONE = (122, 213, 52, 27)   # centre x, y and radii of the ellipse the mouth piece may touch (keeps chin and hair intact)
MOUTH_ZONE_SMALL = (122, 210, 48, 13)   # for the small closed 'pensando' mouth: that image has a chin dimple
DILATE = {"eyes": 6, "mouth": 5}   # grow the changed area so lips/brows/lids are included whole

EMOTIONS = ("feliz", "triste", "curiosa", "surpresa", "confusa")
EYE_PIECES = ("pensando",) + EMOTIONS + ("meio", "pisca")
MOUTH_PIECES = ("a", "o", "e", "u", "pensando") + EMOTIONS


def key(tile):
    a = np.asarray(tile).astype(float)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    alpha = np.clip(1 - (G - np.maximum(R, B) - 25) / 70, 0, 1)
    alpha = ndimage.gaussian_filter(ndimage.minimum_filter(alpha, size=3), 0.7)   # drop the green-contaminated rim
    edge = ndimage.maximum_filter((alpha < 0.98).astype(float), size=5) > 0
    G2 = np.where(edge, np.minimum(G, 0.7 * R + 0.3 * B), G)                       # despill only near the edge
    a[..., 1] = np.minimum(G2, np.maximum(R, B) + 8)
    return a, alpha


def aligned_tiles(path, grid, margin=4):
    cols, rows, label = grid
    im = Image.open(path).convert("RGB")
    tiles = []
    for y0, y1 in rows:
        for x0, x1 in cols:
            rgb, al = key(im.crop((x0 - margin, y0 - margin, x1 + margin, y1 - label)))
            dark = (rgb.max(-1) < 55) & (al > 0.9)
            h = dark.shape[0]
            ys, xs = np.nonzero(dark[int(h * .2):int(h * .75)])
            ys = ys + int(h * .2)
            lo, hi = np.percentile(xs, 1), np.percentile(xs, 99)
            s = REF_W / (hi - lo)
            t = Image.fromarray(np.dstack([rgb, al * 255]).clip(0, 255).astype(np.uint8), "RGBA")
            t = t.resize((round(t.width * s), round(t.height * s)), Image.LANCZOS)
            canvas = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
            canvas.paste(t, (round(REF_C[0] - (lo + hi) / 2 * s), round(REF_C[1] - ys.mean() * s)), t)
            tiles.append(canvas)
    return tiles


def _gray(tile):
    g = cv2.cvtColor(np.asarray(tile)[..., :3], cv2.COLOR_RGB2GRAY).astype(np.float32)
    return cv2.GaussianBlur(g, (0, 0), 1.5)


def _rigid_mask(tile):
    """Head, hair and glasses only: no mouth, chin or shirt, which move with the expression."""
    m = (np.asarray(tile)[..., 3] > 200).astype(np.uint8) * 255
    m = cv2.erode(m, np.ones((7, 7), np.uint8))
    m[REG_BELOW:] = 0
    return m


def register(tile, ref):
    """Move `tile` onto `ref` (small shift + rotation, found by ECC on the rigid parts).

    Aligning only the glasses' width and the mean height of the dark pixels (aligned_tiles) is biased by the
    expression: pupils, lashes and lids are dark too. That left 3-10 px and ~1 deg between frames.
    """
    w = np.eye(2, 3, dtype=np.float32)
    mask = _rigid_mask(ref) & _rigid_mask(tile)
    _, w = cv2.findTransformECC(_gray(ref), _gray(tile), w, cv2.MOTION_EUCLIDEAN,
                                (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-7), mask, 7)
    rgba = np.asarray(tile).astype(np.float32)
    rgba[..., :3] *= rgba[..., 3:] / 255          # premultiply: the warp must not blend in the transparent colour
    out = cv2.warpAffine(rgba, w, (tile.width, tile.height), flags=cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP,
                         borderMode=cv2.BORDER_CONSTANT)
    a = np.clip(out[..., 3:], 1e-3, 255)
    out[..., :3] = np.clip(out[..., :3] * 255 / a, 0, 255)
    print("  registrado: %.1f,%.1f px  %.2f graus" % (w[0, 2], w[1, 2], np.degrees(np.arctan2(w[1, 0], w[0, 0]))))
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def to_screen(tile):
    """224x270 RGBA -> 240x320 RGB on the dark background; the shirt fades out at the bottom."""
    t = tile.resize((240, round(OH * 240 / OW)), Image.LANCZOS)
    a = np.asarray(t).astype(float)
    a[..., 3] *= np.clip((t.height - np.arange(t.height)) / 45, 0, 1)[:, None]
    scr = Image.new("RGB", (240, 320), BG)
    scr.paste(Image.fromarray(a.astype(np.uint8), "RGBA"), (0, 14), Image.fromarray(a.astype(np.uint8), "RGBA"))
    return np.asarray(scr).astype(float)


BAYER = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16 - 0.5


def raw565(rgb, x0=0, y0=0):
    """float RGB region -> RGB565 big-endian bytes, with ordered dither anchored to absolute screen coordinates."""
    h, w = rgb.shape[:2]
    t = BAYER[(np.arange(h) + y0)[:, None] % 4, (np.arange(w) + x0)[None, :] % 4]
    a = np.clip(rgb + t[..., None] * np.array([8.2, 4.1, 8.2]), 0, 255).astype(int)
    return (((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)).astype(">u2").tobytes()


def blended(neutral, src, box, grow, zone=None):
    """Neutral face with only the pixels that really change (lips, brows, lids...) replaced by `src`.

    A plain rectangle cut through the jaw/hair outline, which differs a little between the generated images, and left
    visible steps; and brows higher than the box left a ghost of the neutral brow. The mask follows the features instead.
    """
    x0, y0, x1, y1 = box
    h, w = y1 - y0, x1 - x0
    n, s = neutral[y0:y1], src[y0:y1]
    changed = (np.abs(s[:, x0:x1] - n[:, x0:x1]).sum(-1) > DIFF_THR)
    changed = ndimage.binary_opening(changed, iterations=1)        # drop isolated noise pixels
    mask = ndimage.binary_dilation(changed, iterations=grow).astype(float)
    if zone:  # the jaw/hair outline differs between the generated images: never let a piece reach it
        cx, cy, rx, ry = zone
        yy, xx = np.mgrid[y0:y1, x0:x1]
        mask *= np.clip((1 - np.hypot((xx - cx) / rx, (yy - cy) / ry)) / 0.2, 0, 1)
    alpha = ndimage.gaussian_filter(mask, 2.5)
    y = np.minimum(np.arange(h), np.arange(h)[::-1])[:, None]
    x = np.minimum(np.arange(w), np.arange(w)[::-1])[None, :]
    alpha = (alpha * np.clip(np.minimum(x, y) / FEATHER, 0, 1))[..., None]   # always 0 at the box border
    return alpha * s[:, x0:x1] + (1 - alpha) * n[:, x0:x1]


def main():
    os.makedirs(OUT, exist_ok=True)
    tiles = aligned_tiles(SPRITE_SHEET, SPRITE_GRID, margin=0)
    names = {i - 1: n for n, i in SPRITE.items()}
    ref = tiles[SPRITE["neutra"] - 1]
    registered = {}
    for i, t in enumerate(tiles):
        print(names[i])
        registered[names[i]] = t if names[i] == "neutra" else register(t, ref)
    print("confusa (folha antiga)")
    registered["confusa"] = register(aligned_tiles(OLD_SHEET, OLD_GRID)[OLD_CONFUSA - 1], ref)
    frames = {name: to_screen(t) for name, t in registered.items()}
    neutral = frames["neutra"]
    y0, y1 = HAIR_TOP                       # same hair crown on every frame
    w = np.clip((np.arange(320) - y0) / (y1 - y0), 0, 1)[:, None, None]
    for name, f in frames.items():
        if name != "neutra":
            frames[name] = np.where(np.arange(320)[:, None, None] < y1, (1 - w) * neutral + w * f, f)
    files = {"neutra": raw565(neutral)}
    files["e_neutra"] = raw565(neutral[EYES[1]:EYES[3], EYES[0]:EYES[2]], EYES[0], EYES[1])
    for name in EYE_PIECES:
        files["e_" + name] = raw565(blended(neutral, frames[name], EYES, DILATE["eyes"]), EYES[0], EYES[1])
    files["m_fechada"] = raw565(neutral[MOUTH[1]:MOUTH[3], MOUTH[0]:MOUTH[2]], MOUTH[0], MOUTH[1])
    for name in MOUTH_PIECES:
        zone = MOUTH_ZONE_SMALL if name == "pensando" else MOUTH_ZONE
        files["m_" + name] = raw565(blended(neutral, frames[name], MOUTH, DILATE["mouth"], zone), MOUTH[0], MOUTH[1])
    for stale in os.listdir(OUT):   # images of the old "swap the whole screen" scheme
        if stale.endswith(".raw") and stale[:-4] not in files:
            os.remove(os.path.join(OUT, stale))
    total = 0
    for name, data in files.items():
        with open(os.path.join(OUT, name + ".raw"), "wb") as f:
            f.write(data)
        total += len(data)
    print("%d arquivos, %.2f MB em %s" % (len(files), total / 1048576, os.path.relpath(OUT)))


if __name__ == "__main__":
    main()
