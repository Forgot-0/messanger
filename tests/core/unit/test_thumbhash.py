import base64
import math

import pytest

from app.core.services.media.thumbhash import encode_thumbhash, rgba_to_thumbhash


def average_rgba(hash_bytes: bytes) -> tuple[float, float, float, float]:
    """`thumbHashToAverageRGBA` из эталонной реализации."""
    header = hash_bytes[0] | (hash_bytes[1] << 8) | (hash_bytes[2] << 16)
    lum = (header & 63) / 63
    p = ((header >> 6) & 63) / 31.5 - 1
    q = ((header >> 12) & 63) / 31.5 - 1
    has_alpha = header >> 23
    alpha = (hash_bytes[5] & 15) / 15 if has_alpha else 1.0
    b = lum - 2 / 3 * p
    r = (3 * lum - b + q) / 2
    g = r - q
    return max(0.0, min(1.0, r)), max(0.0, min(1.0, g)), max(0.0, min(1.0, b)), alpha


def aspect_ratio(hash_bytes: bytes) -> float:
    """`thumbHashToApproximateAspectRatio` из эталонной реализации."""
    header = hash_bytes[3]
    has_alpha = hash_bytes[2] & 0x80
    is_landscape = hash_bytes[4] & 0x80
    lx = (5 if has_alpha else 7) if is_landscape else header & 7
    ly = header & 7 if is_landscape else (5 if has_alpha else 7)
    return lx / ly


def decode(hash_bytes: bytes) -> tuple[int, int, list[tuple[float, float, float]]]:
    """`thumbHashToRGBA` из эталонной реализации (без альфы): картинка ≤32px по большей стороне."""
    header24 = hash_bytes[0] | (hash_bytes[1] << 8) | (hash_bytes[2] << 16)
    header16 = hash_bytes[3] | (hash_bytes[4] << 8)
    l_dc = (header24 & 63) / 63
    p_dc = ((header24 >> 6) & 63) / 31.5 - 1
    q_dc = ((header24 >> 12) & 63) / 31.5 - 1
    l_scale = ((header24 >> 18) & 31) / 31
    assert not header24 >> 23
    p_scale = ((header16 >> 3) & 63) / 63
    q_scale = ((header16 >> 9) & 63) / 63
    is_landscape = header16 >> 15
    lx = max(3, 7 if is_landscape else header16 & 7)
    ly = max(3, header16 & 7 if is_landscape else 7)

    index = 0

    def channel(nx: int, ny: int, scale: float) -> list[float]:
        nonlocal index
        values = []
        for cy in range(ny):
            cx = 0 if cy else 1
            while cx * ny < nx * (ny - cy):
                nibble = (hash_bytes[5 + (index >> 1)] >> ((index & 1) << 2)) & 15
                values.append((nibble / 7.5 - 1) * scale)
                index += 1
                cx += 1
        return values

    l_ac = channel(lx, ly, l_scale)
    p_ac = channel(3, 3, p_scale * 1.25)
    q_ac = channel(3, 3, q_scale * 1.25)

    ratio = aspect_ratio(hash_bytes)
    w = round(32 if ratio > 1 else 32 * ratio)
    h = round(32 / ratio if ratio > 1 else 32)
    pixels = []
    for y in range(h):
        for x in range(w):
            fx = [math.cos(math.pi / w * (x + 0.5) * cx) for cx in range(max(lx, 3))]
            fy = [math.cos(math.pi / h * (y + 0.5) * cy) for cy in range(max(ly, 3))]
            lum, p, q, j = l_dc, p_dc, q_dc, 0
            for cy in range(ly):
                cx = 0 if cy else 1
                while cx * ly < lx * (ly - cy):
                    lum += l_ac[j] * fx[cx] * fy[cy] * 2
                    j += 1
                    cx += 1
            j = 0
            for cy in range(3):
                for cx in range(0 if cy else 1, 3 - cy):
                    p += p_ac[j] * fx[cx] * fy[cy] * 2
                    q += q_ac[j] * fx[cx] * fy[cy] * 2
                    j += 1
            b = lum - 2 / 3 * p
            r = (3 * lum - b + q) / 2
            pixels.append((r, r - q, b))
    return w, h, pixels


def solid(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    return bytes(rgba) * (width * height)


@pytest.mark.unit
class TestThumbhash:

    @pytest.mark.parametrize("color", [(200, 30, 30, 255), (20, 160, 90, 255), (240, 240, 240, 255)])
    def test_average_color_survives_the_round_trip(self, color: tuple[int, int, int, int]) -> None:
        hashed = rgba_to_thumbhash(32, 24, solid(32, 24, color))

        r, g, b, a = average_rgba(hashed)

        assert abs(r - color[0] / 255) < 0.04
        assert abs(g - color[1] / 255) < 0.04
        assert abs(b - color[2] / 255) < 0.04
        assert a == 1.0

    @pytest.mark.parametrize(
        "width,height,expected",
        [(100, 50, 7 / 4), (50, 100, 4 / 7), (100, 100, 1.0)],
    )
    def test_aspect_ratio_is_encoded(self, width: int, height: int, expected: float) -> None:
        hashed = rgba_to_thumbhash(width, height, solid(width, height, (90, 90, 200, 255)))

        assert aspect_ratio(hashed) == pytest.approx(expected, abs=0.01)

    def test_gradient_survives_the_round_trip(self) -> None:
        """Декодер эталона восстанавливает градиент слева направо: значит, AC-коэффициенты
        упакованы в том же порядке и с тем же сдвигом полубайтов, что ждут клиенты."""
        width, height = 64, 32
        rgba = bytes(
            channel
            for _y in range(height)
            for x in range(width)
            for channel in (round(255 * x / (width - 1)), 40, round(255 * (1 - x / (width - 1))), 255)
        )

        w, h, pixels = decode(rgba_to_thumbhash(width, height, rgba))

        assert (w, h) == (32, 18)
        left = pixels[(h // 2) * w + 1]
        right = pixels[(h // 2) * w + w - 2]
        assert left[0] < 0.25 < 0.75 < right[0]
        assert left[2] > 0.75 > 0.25 > right[2]

    def test_opaque_image_has_no_alpha_byte(self) -> None:
        hashed = rgba_to_thumbhash(16, 16, solid(16, 16, (10, 20, 30, 255)))

        assert hashed[2] & 0x80 == 0
        # 5 байт заголовка + 4 бита на каждый AC-коэффициент L (7×7 треугольник без DC) и P/Q (по 5).
        assert len(hashed) == 5 + (27 + 5 + 5 + 1) // 2

    def test_transparency_is_flagged_and_averaged(self) -> None:
        half = solid(8, 16, (0, 0, 0, 0)) + solid(8, 16, (255, 255, 255, 255))

        hashed = rgba_to_thumbhash(16, 16, half)

        assert hashed[2] & 0x80
        assert average_rgba(hashed)[3] == pytest.approx(0.5, abs=0.07)

    def test_encoding_is_deterministic_and_base64(self) -> None:
        pixels = bytes((x * 7 + y * 3) % 256 for y in range(40) for x in range(60 * 4))

        first = encode_thumbhash(60, 40, pixels)

        assert first == encode_thumbhash(60, 40, pixels)
        assert base64.b64decode(first) == rgba_to_thumbhash(60, 40, pixels)

    @pytest.mark.parametrize("width,height", [(101, 10), (10, 101), (0, 10)])
    def test_out_of_range_sizes_are_refused(self, width: int, height: int) -> None:
        with pytest.raises(ValueError):
            rgba_to_thumbhash(width, height, b"\x00" * max(0, width * height * 4))

    def test_buffer_size_must_match(self) -> None:
        with pytest.raises(ValueError):
            rgba_to_thumbhash(4, 4, b"\x00" * 10)
