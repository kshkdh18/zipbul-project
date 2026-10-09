import socket
import struct
import threading

import pytest

from zipcontrol.protocol import DOWN, MOVE, UP, Packet, Session, read_exact, read_packet, touch


def test_touch_matches_scrcpy_41_wire_contract():
    # Type, action, 64-bit pointer, x/y, source video width/height, pressure, two button fields.
    expected = bytes.fromhex("02 00 0000000000000001 00000064 000000c8 032a 0500 ffff 00000000 00000000")
    assert touch(DOWN, 1, 100, 200, 810, 1280) == expected
    up = touch(UP, 2, 100, 200, 810, 1280)
    assert len(up) == 32 and up[1] == 1 and up[22:24] == b"\0\0"


def test_video_parser_handles_fragmentation_session_and_config():
    reader, writer = socket.socketpair()
    raw = struct.pack(">III", 0x80000000, 810, 1280)
    raw += struct.pack(">QI", 1 << 62, 3) + b"cfg"
    raw += struct.pack(">QI", (1 << 61) | 123456, 5) + b"frame"

    def produce():
        for byte in raw:
            writer.sendall(bytes([byte]))
        writer.close()

    t = threading.Thread(target=produce)
    t.start()
    try:
        assert read_packet(reader) == Session(810, 1280)
        assert read_packet(reader) == Packet(b"cfg", 0, True, False)
        assert read_packet(reader) == Packet(b"frame", 123456, False, True)
        with pytest.raises(EOFError):
            read_exact(reader, 1)
    finally:
        reader.close()
        t.join()


@pytest.mark.parametrize("x,y", [(-1, 0), (810, 0), (0, 1280)])
def test_outside_video_rejected(x, y):
    with pytest.raises(ValueError):
        touch(MOVE, 1, x, y, 810, 1280)


def test_bad_packet_length_does_not_allocate_payload():
    a, b = socket.socketpair()
    try:
        b.sendall(struct.pack(">QI", 0, 0xFFFFFFFF))
        with pytest.raises(ValueError):
            read_packet(a)
    finally:
        a.close()
        b.close()
