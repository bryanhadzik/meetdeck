"""The database password stored in a Jet 4 (.mdb) file header, so Windows' Access driver can open
Meet Manager files (the Java library reads them without it). Same steps as Jackcess / mdbtools:
the header from 0x18 is RC4-masked with key 0x6b39dac7; the password (UTF-16, 40 bytes at 0x42) is
further XORed with the file's creation date (double at 0x72, as a 4-byte int)."""
import struct


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 255
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) & 255
        j = (j + s[i]) & 255
        s[i], s[j] = s[j], s[i]
        out.append(b ^ s[(s[i] + s[j]) & 255])
    return bytes(out)


def password(path) -> str:
    with open(path, "rb") as f:
        hdr = bytearray(f.read(0x100))
    jet3 = hdr[0x14] == 0
    hdr[0x18:0x18 + (126 if jet3 else 128)] = _rc4(struct.pack("<I", 0x6B39DAC7), bytes(hdr[0x18:0x18 + (126 if jet3 else 128)]))
    if jet3:
        pw = bytes(hdr[0x42:0x42 + 20])
        return pw.split(b"\0", 1)[0].decode("latin-1")
    pw = bytearray(hdr[0x42:0x42 + 40])
    mask = struct.pack("<i", int(struct.unpack("<d", bytes(hdr[0x72:0x7A]))[0]))
    for i in range(len(pw)):
        pw[i] ^= mask[i % 4]
    s = pw.decode("utf-16-le", "replace")
    return s.split("\0", 1)[0]
