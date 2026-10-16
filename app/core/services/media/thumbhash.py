import base64
import math
from collections.abc import Sequence

MAX_SIDE = 100


def _round(value: float) -> int:
    return math.floor(value + 0.5)


def _encode_channel(
    channel: Sequence[float], width: int, height: int, nx: int, ny: int
) -> tuple[float, list[float], float]:
    rows = [channel[y * width:(y + 1) * width] for y in range(height)]
    dc = 0.0
    ac: list[float] = []
    scale = 0.0

    for cy in range(ny):
        fy = [math.cos(math.pi / height * cy * (y + 0.5)) for y in range(height)]
        cx = 0
        while cx * ny < nx * (ny - cy):
            fx = [math.cos(math.pi / width * cx * (x + 0.5)) for x in range(width)]
            row_sums = [math.sumprod(row, fx) for row in rows]
            f = math.sumprod(row_sums, fy) / (width * height)
            if cx or cy:
                ac.append(f)
                scale = max(scale, abs(f))
            else:
                dc = f
            cx += 1

    if scale:
        ac = [0.5 + 0.5 / scale * value for value in ac]
    return dc, ac, scale


def rgba_to_thumbhash(width: int, height: int, rgba: bytes) -> bytes:
    if width <= 0 or height <= 0:
        raise ValueError("image must not be empty")
    if width > MAX_SIDE or height > MAX_SIDE:
        raise ValueError(f"{width}x{height} doesn't fit in {MAX_SIDE}x{MAX_SIDE}")
    if len(rgba) != width * height * 4:
        raise ValueError("rgba buffer does not match the image size")

    pixels = width * height
    alpha = [rgba[i + 3] / 255 for i in range(0, pixels * 4, 4)]

    avg_r = avg_g = avg_b = avg_a = 0.0
    for i in range(pixels):
        a = alpha[i]
        j = i * 4
        avg_r += a / 255 * rgba[j]
        avg_g += a / 255 * rgba[j + 1]
        avg_b += a / 255 * rgba[j + 2]
        avg_a += a
    if avg_a:
        avg_r /= avg_a
        avg_g /= avg_a
        avg_b /= avg_a

    has_alpha = avg_a < pixels
    l_limit = 5 if has_alpha else 7
    lx = max(1, _round(l_limit * width / max(width, height)))
    ly = max(1, _round(l_limit * height / max(width, height)))

    lum: list[float] = [0.0] * pixels
    p: list[float] = [0.0] * pixels
    q: list[float] = [0.0] * pixels
    for i in range(pixels):
        a = alpha[i]
        j = i * 4
        r = avg_r * (1 - a) + a / 255 * rgba[j]
        g = avg_g * (1 - a) + a / 255 * rgba[j + 1]
        b = avg_b * (1 - a) + a / 255 * rgba[j + 2]
        lum[i] = (r + g + b) / 3
        p[i] = (r + g) / 2 - b
        q[i] = r - g

    l_dc, l_ac, l_scale = _encode_channel(lum, width, height, max(3, lx), max(3, ly))
    p_dc, p_ac, p_scale = _encode_channel(p, width, height, 3, 3)
    q_dc, q_ac, q_scale = _encode_channel(q, width, height, 3, 3)
    a_dc, a_ac, a_scale = _encode_channel(alpha, width, height, 5, 5) if has_alpha else (0.0, [], 0.0)

    is_landscape = width > height
    header24 = (
        _round(63 * l_dc)
        | (_round(31.5 + 31.5 * p_dc) << 6)
        | (_round(31.5 + 31.5 * q_dc) << 12)
        | (_round(31 * l_scale) << 18)
        | (int(has_alpha) << 23)
    )
    header16 = (
        (ly if is_landscape else lx)
        | (_round(63 * p_scale) << 3)
        | (_round(63 * q_scale) << 9)
        | (int(is_landscape) << 15)
    )
    hash_bytes = [header24 & 255, (header24 >> 8) & 255, header24 >> 16, header16 & 255, header16 >> 8]
    if has_alpha:
        hash_bytes.append(_round(15 * a_dc) | (_round(15 * a_scale) << 4))

    ac_start = len(hash_bytes)
    factors = [*l_ac, *p_ac, *q_ac, *(a_ac if has_alpha else [])]
    hash_bytes.extend([0] * ((len(factors) + 1) // 2))
    for index, factor in enumerate(factors):
        hash_bytes[ac_start + (index >> 1)] |= _round(15 * factor) << ((index & 1) << 2)

    return bytes(hash_bytes)


def encode_thumbhash(width: int, height: int, rgba: bytes) -> str:
    return base64.b64encode(rgba_to_thumbhash(width, height, rgba)).decode("ascii")
