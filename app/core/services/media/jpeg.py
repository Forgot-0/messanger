"""Вырезание метаданных из JPEG без перекодирования.

Сканы копируются байт в байт, выбрасываются APP1 (EXIF и XMP — там GPS, модель камеры),
APP13 (IPTC/Photoshop), остальные APPn, COM и всё, что лежит после EOI (MPF-превью,
«живые фото» Samsung). Остаются JFIF, ICC-профиль и Adobe APP14: без них меняются цвета.
Вместе с EXIF уходит и тег поворота — файлы с orientation ≠ 1 сюда передавать нельзя.
"""

SOI = b"\xff\xd8"
EOI = 0xD9
SOS = 0xDA
APP0 = 0xE0
APP2 = 0xE2
APP14 = 0xEE
APP15 = 0xEF
COM = 0xFE
STANDALONE = frozenset({0x01, *range(0xD0, 0xD8)})


def strip_jpeg_metadata(data: bytes) -> bytes | None:
    """Чистый JPEG или `None`, если структура не читается (тогда — перекодировать)."""
    if not data.startswith(SOI):
        return None

    out = bytearray(SOI)
    pos, size = 2, len(data)
    while pos < size:
        if data[pos] != 0xFF:
            return None
        while pos < size and data[pos] == 0xFF:
            pos += 1
        if pos >= size:
            return None

        marker = data[pos]
        pos += 1
        if marker == EOI:
            out += b"\xff\xd9"
            return bytes(out)
        if marker in STANDALONE:
            out += bytes((0xFF, marker))
            continue

        if pos + 2 > size:
            return None
        length = int.from_bytes(data[pos:pos + 2], "big")
        end = pos + length
        if length < 2 or end > size:
            return None

        if _keep(data, marker, pos + 2):
            out += bytes((0xFF, marker))
            out += data[pos:end]
        pos = end

        if marker == SOS:
            scan_end = _entropy_end(data, pos)
            if scan_end is None:
                return None
            out += data[pos:scan_end]
            pos = scan_end

    return None


def _keep(data: bytes, marker: int, payload: int) -> bool:
    if marker == APP0:
        return data.startswith(b"JFIF\x00", payload)
    if marker == APP2:
        return data.startswith(b"ICC_PROFILE\x00", payload)
    if marker == APP14:
        return data.startswith(b"Adobe", payload)
    return not (APP0 <= marker <= APP15 or marker == COM)


def _entropy_end(data: bytes, pos: int) -> int | None:
    """Внутри скана 0xFF встречается только как `FF 00` (stuffing) или `FF D0..D7` (RST);
    любой другой байт после 0xFF — начало следующего маркера."""
    while True:
        index = data.find(b"\xff", pos)
        if index < 0 or index + 1 >= len(data):
            return None
        following = data[index + 1]
        if following == 0x00 or 0xD0 <= following <= 0xD7:
            pos = index + 2
            continue
        return index
