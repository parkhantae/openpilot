"""Local native-test adapter; no vehicle connection."""
import ctypes
from pathlib import Path
import struct
import os
import shlex
import subprocess
import tempfile

_temp = None
if os.environ.get("PORTER_SAFETY_LIB"):
    library = Path(os.environ["PORTER_SAFETY_LIB"]).resolve()
else:
    _temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    library = Path(_temp.name) / ("porter.dll" if os.name == "nt" else "porter.so")
    safety = Path(__file__).resolve().parents[1]
    compiler = shlex.split(os.environ.get("CC", "cc"))
    subprocess.run([*compiler, "-shared", "-fPIC", "-O0", "-std=gnu11",
                    f"-I{safety / 'board'}", f"-I{safety}", f"-I{safety / 'tests'}",
                    f"-I{safety / 'tests/libsafety'}", str(safety / "tests/hyundai_porter.c"),
                    "-o", str(library)], check=True)
lib = ctypes.CDLL(str(library))
for name in ('safety_rx_hook', 'safety_tx_hook'):
    getattr(lib, name).argtypes = [ctypes.c_void_p]
    getattr(lib, name).restype = ctypes.c_bool
lib.set_safety_hooks.argtypes = [ctypes.c_uint16, ctypes.c_uint16]
lib.set_safety_hooks.restype = ctypes.c_int
lib.set_timer.argtypes = [ctypes.c_uint32]
lib.can_set_checksum.argtypes = [ctypes.c_void_p]
for name in ('get_controls_allowed', 'safety_config_valid'):
    getattr(lib, name).restype = ctypes.c_bool


def packet(address, payload, bus=0):
    result = (ctypes.c_uint8 * 72)()
    result[0] = (len(payload) << 4) | (bus << 1)
    struct.pack_into('<I', result, 1, address << 3)
    result[6:6+len(payload)] = payload
    lib.can_set_checksum(result)
    return result


def data(address, target=0, button=0, brake=False, gas=False, drive=True, hold=False, park=False, counter=0):
    value = 0
    if address == 0x371:
        value = (target << 23) | (int(gas) << 31)
    elif address == 0x394:
        value = (counter % 8 << 13) | (int(brake) * 2 << 45) | (int(park) << 53) | (int(brake) << 55)
    elif address == 0x386:
        value = ((counter % 16 & 3) << 14) | ((counter % 16 >> 2) << 30)
    elif address == 0x4f1:
        value = button | ((counter % 16) << 28)
    elif address == 0x372:
        value = (5 if drive else 0) << 16
    elif address == 0x507:
        value = (2 if hold else 0) << 29
    payload = bytearray(value.to_bytes(4 if address in (0x4f1,0x507) else 8, 'little'))
    if address == 0x394:
        checksum = (16 - sum((b & 15) + (b >> 4) for b in payload[:7])) % 16
        payload[6] |= checksum
    if address == 0x386:
        checksum = (sum((b & 0x3f if i in (1, 3, 5, 7) else b).bit_count() for i, b in enumerate(payload)) ^ 9) & 15
        payload[5] |= (checksum & 3) << 6
        payload[7] |= (checksum >> 2) << 6
    return bytes(payload)


def rx(address, bus=0, **kwargs):
    return lib.safety_rx_hook(packet(address, data(address, **kwargs), bus))


def seed(target=0, counter=0, **kwargs):
    for address in (0x386,0x394,0x4f1,0x372,0x507,0x371):
        assert rx(address, target=target, counter=counter, **kwargs), hex(address)


def init():
    assert lib.set_safety_hooks(8, 1025) == 0
    lib.init_tests()
    lib.set_timer(1000)
    seed()
    assert lib.safety_config_valid()


def engage():
    init()
    lib.set_timer(2000)
    seed(counter=1, button=2)
    lib.set_timer(3000)
    seed(counter=2, target=31)
    assert lib.get_controls_allowed()

