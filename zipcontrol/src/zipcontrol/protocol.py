"""Wire format pinned to Genymobile/scrcpy v4.1 (not the legacy 1.x protocol)."""

import socket
import struct
from dataclasses import dataclass

VERSION = "4.1"
DOWN, UP, MOVE = 0, 1, 2
MAX_PACKET = 16 * 1024 * 1024


def read_exact(sock: socket.socket, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        chunk = sock.recv(count - len(chunks))
        if not chunk:
            raise EOFError("scrcpy connection closed")
        chunks.extend(chunk)
    return bytes(chunks)


@dataclass(frozen=True)
class Session:
    width: int
    height: int


@dataclass(frozen=True)
class Packet:
    data: bytes
    pts: int
    config: bool
    keyframe: bool


def read_packet(sock: socket.socket) -> Session | Packet:
    header = read_exact(sock, 12)
    if header[0] & 0x80:
        _, width, height = struct.unpack(">III", header)
        if not (0 < width <= 65535 and 0 < height <= 65535):
            raise ValueError(f"Invalid scrcpy geometry: {width}x{height}")
        return Session(width, height)
    flags, size = struct.unpack(">QI", header)
    if not 0 < size <= MAX_PACKET:
        raise ValueError(f"Invalid scrcpy packet length: {size}")
    return Packet(
        read_exact(sock, size), flags & ((1 << 61) - 1), bool(flags & (1 << 62)), bool(flags & (1 << 61))
    )


def touch(action: int, pointer: int, x: float, y: float, width: int, height: int) -> bytes:
    """One 32-byte INJECT_TOUCH_EVENT; the server assembles Android pointer arrays."""
    if action not in (DOWN, MOVE, UP) or not 0 <= pointer < (1 << 63):
        raise ValueError("Invalid touch action or pointer ID")
    if not (0 < width <= 65535 and 0 < height <= 65535):
        raise ValueError("Invalid touch geometry")
    x, y = round(x), round(y)
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(f"Touch outside frame: {x},{y} in {width}x{height}")
    return struct.pack(
        ">BBQiiHHHII", 2, action, pointer, x, y, width, height, 0 if action == UP else 65535, 0, 0
    )
