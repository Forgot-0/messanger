import struct

import pytest
import pyvips  # type: ignore[import-untyped]

from app.core.services.media.jpeg import strip_jpeg_metadata
from tests.support.media import GPS_LATITUDE, make_jpeg, solid_image


def segment(marker: int, payload: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def with_segments(jpeg: bytes, *segments: bytes) -> bytes:
    return jpeg[:2] + b"".join(segments) + jpeg[2:]


def same_pixels(left: bytes, right: bytes) -> bool:
    a = pyvips.Image.new_from_buffer(left, "")
    b = pyvips.Image.new_from_buffer(right, "")
    return (a.width, a.height) == (b.width, b.height) and (a - b).abs().max() == 0


@pytest.mark.unit
class TestStripJpegMetadata:

    def test_clean_jpeg_comes_back_byte_for_byte(self) -> None:
        plain = make_jpeg(320, 240)

        assert strip_jpeg_metadata(plain) == plain

    def test_exif_with_gps_is_cut_out_and_pixels_are_untouched(self) -> None:
        plain = make_jpeg(320, 240)
        tagged = make_jpeg(320, 240, orientation=1, gps=True)

        stripped = strip_jpeg_metadata(tagged)

        assert stripped == plain
        assert GPS_LATITUDE not in stripped
        assert same_pixels(stripped, tagged)

    @pytest.mark.parametrize(
        "dropped",
        [
            segment(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>GPS</x:xmpmeta>"),
            segment(0xED, b"Photoshop 3.0\x008BIM iptc"),
            segment(0xFE, b"shot on a secret camera"),
            segment(0xE2, b"MPF\x00multi-picture index"),
            segment(0xE0, b"JFXX\x00\x10thumbnail"),
            segment(0xEC, b"Ducky\x00quality"),
        ],
    )
    def test_metadata_segments_are_dropped(self, dropped: bytes) -> None:
        plain = make_jpeg(64, 48)

        assert strip_jpeg_metadata(with_segments(plain, dropped)) == plain

    def test_colour_segments_are_kept(self) -> None:
        plain = make_jpeg(64, 48)
        icc = segment(0xE2, b"ICC_PROFILE\x00\x01\x01profile-bytes")
        adobe = segment(0xEE, b"Adobe\x00\x64\x00\x00\x00\x00\x01")

        stripped = strip_jpeg_metadata(with_segments(plain, icc, adobe))

        assert stripped is not None
        assert icc in stripped and adobe in stripped

    def test_data_after_the_end_of_image_is_dropped(self) -> None:
        """Samsung дописывает «живое фото» (MP4) за EOI, MPF — вторые картинки."""
        plain = make_jpeg(64, 48)

        assert strip_jpeg_metadata(plain + b"MotionPhoto_Data" + b"\x00" * 64) == plain

    def test_progressive_jpeg_survives(self) -> None:
        progressive = solid_image(300, 200).write_to_buffer(
            ".jpg", Q=85, interlace=True, keep=pyvips.enums.ForeignKeep.NONE
        )
        tagged = with_segments(progressive, segment(0xE1, b"Exif\x00\x00" + b"\x00" * 32))

        stripped = strip_jpeg_metadata(tagged)

        assert stripped == progressive

    def test_restart_markers_inside_the_scan_are_kept(self) -> None:
        with_restarts = solid_image(256, 256).write_to_buffer(
            ".jpg", Q=85, restart_interval=2, keep=pyvips.enums.ForeignKeep.NONE
        )
        assert b"\xff\xd0" in with_restarts

        assert strip_jpeg_metadata(with_segments(with_restarts, segment(0xFE, b"c"))) == with_restarts

    def test_fill_bytes_before_a_marker_are_tolerated(self) -> None:
        plain = make_jpeg(64, 48)
        padded = plain[:2] + b"\xff\xff" + segment(0xE1, b"Exif\x00\x00")[1:] + plain[2:]

        assert strip_jpeg_metadata(padded) == plain

    @pytest.mark.parametrize(
        "data",
        [
            b"",
            b"GIF89a",
            b"\xff\xd8",
            b"\xff\xd8\xff\xe1\x00",
            b"\xff\xd8\xff\xe1\xff\xff",
            b"\xff\xd8\x00\x00",
        ],
    )
    def test_unreadable_structure_is_reported(self, data: bytes) -> None:
        assert strip_jpeg_metadata(data) is None

    def test_truncated_scan_is_reported(self) -> None:
        plain = make_jpeg(320, 240)

        assert strip_jpeg_metadata(plain[: len(plain) // 2]) is None
