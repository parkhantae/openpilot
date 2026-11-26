"""Host packet fields and array strides must match the native firmware ABI."""
import pytest

from opendbc.safety import LEN_TO_DLC
from opendbc.safety.tests.libsafety.libsafety_py import ffi, libsafety


def test_packet_size_offset_alignment_and_array_stride():
  assert ffi.sizeof('CANPacket_t') == libsafety.safety_test_packet_size() == 72
  assert ffi.offsetof('CANPacket_t', 'data') == libsafety.safety_test_packet_data_offset() == 6
  packets = ffi.new('CANPacket_t[2]')
  assert int(ffi.cast('uintptr_t', packets)) % 4 == 0
  packets[1].addr = 0x12345
  assert libsafety.safety_test_second_packet_addr(packets) == 0x12345


@pytest.mark.parametrize('address', [0x12A, 0x1CF, 0x1ABCDEFF])
@pytest.mark.parametrize('bus', [0, 1, 2, 3])
@pytest.mark.parametrize('length', [0, 8, 16, 32, 64])
def test_native_reads_the_same_bitfields_and_payload(address, bus, length):
  packet = ffi.new('CANPacket_t *')
  packet.addr, packet.bus, packet.data_len_code = address, bus, LEN_TO_DLC[length]
  packet.extended = address >= 0x800
  assert libsafety.safety_test_packet_addr(packet) == address
  assert libsafety.safety_test_packet_bus(packet) == bus
  assert libsafety.safety_test_packet_len(packet) == length
