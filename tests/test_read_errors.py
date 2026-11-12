"""The typed read errors: `byte_reader.ReadError` (a ValueError) and one
subclass per reading module, raised where the bytes do not read, with the
messages the bare ValueError carried."""

import struct

import pytest

import byte_reader
import kapow_block
import model_header
import naz_archive
import sound_header
import texture_header

TYPED = [
    naz_archive.ArchiveError,
    kapow_block.BlockError,
    texture_header.TextureHeaderError,
    model_header.ModelHeaderError,
    sound_header.SoundHeaderError,
]


@pytest.mark.parametrize("cls", TYPED, ids=lambda c: c.__name__)
def test_typed_errors_are_read_errors(cls):
    assert issubclass(cls, byte_reader.ReadError)
    assert issubclass(cls, ValueError)


def test_byte_reader_past_end():
    r = byte_reader.ByteReader(b"\x01\x00")
    with pytest.raises(byte_reader.ReadError, match="read past end"):
        r.u32()
    with pytest.raises(byte_reader.ReadError, match="bool 2"):
        byte_reader.ByteReader(b"\x02").boolean()
    with pytest.raises(byte_reader.ReadError, match="count 9"):
        byte_reader.ByteReader(struct.pack("<I", 9)).count(1)


def test_archive_error_not_a_naz(tmp_path):
    p = tmp_path / "short.naz"
    p.write_bytes(b"\0" * 4)
    with pytest.raises(naz_archive.ArchiveError, match="not a NAZ archive"):
        list(naz_archive.naz_entries(p))


def test_archive_error_inflate_ceiling():
    import zlib

    with pytest.raises(naz_archive.ArchiveError, match="inflates past 16 bytes"):
        naz_archive.inflate(zlib.compress(bytes(64)), limit=16)


def test_block_error_short_header():
    with pytest.raises(kapow_block.BlockError, match="not a block header"):
        kapow_block.parse_block_header(b"\0" * 8)


def test_model_header_error_primitive_type():
    with pytest.raises(model_header.ModelHeaderError, match="primitive type 7"):
        model_header.index_triangles([0, 1, 2], 7)


def test_texture_header_error_count():
    # serial, the cycle head, then a step count the remaining bytes cannot hold
    tail = struct.pack("<5I", 1, 0, 0, 0, 1000)
    with pytest.raises(texture_header.TextureHeaderError, match="count 1000"):
        texture_header._parse_texture_anim_tail(tail, 0)
