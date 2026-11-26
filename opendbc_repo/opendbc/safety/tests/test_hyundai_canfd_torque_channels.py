"""Keep real HDA2 host streams, without sharing torque or request-bit credit."""
from types import SimpleNamespace as NS

import pytest

from opendbc.car.hyundai import hyundaicanfd
from opendbc.car.hyundai.values import HyundaiFlags
from opendbc.safety.tests.libsafety.libsafety_py import make_CANPacket
from opendbc.safety.tests.test_hyundai_canfd_authorization import Hooks, native as native_fixture

native = native_fixture


@pytest.mark.parametrize('longitudinal', [False, True])
def test_real_camera_scc_host_lfa_is_authorized_in_stock_and_openpilot_long(native, longitudinal):
  h = Hooks(native, 25 | (4 if longitudinal else 0), strict=False)
  h.engage()
  cp = NS(flags=HyundaiFlags.CANFD_HDA2 | HyundaiFlags.CAMERA_SCC, openpilotLongitudinalControl=longitudinal)
  cs = NS(adrv_0x161=None, mdps=None, lfa={})
  packets = hyundaicanfd.create_steering_messages_camera_scc(
    1, h.packer, cp, NS(ECAN=0, ACAN=1, CAM=2), NS(latActive=True), True, 2, cs, 0., 0., False)
  assert [(addr, bus) for addr, _, bus in packets] == [(0x12A, 0)]
  assert all(h.tx(make_CANPacket(addr, bus, data)) for addr, data, bus in packets)


@pytest.mark.parametrize('alt', [False, True])
def test_real_hda2_long_host_keeps_both_authorized_torque_streams(native, alt):
  h = Hooks(native, 21 | (128 if alt else 0), strict=False)
  h.engage()
  flags = HyundaiFlags.CANFD_HDA2 | (HyundaiFlags.CANFD_HDA2_ALT_STEERING if alt else 0)
  cp = NS(flags=flags, openpilotLongitudinalControl=True)
  packets = hyundaicanfd.create_steering_messages(h.packer, cp, NS(ECAN=1, ACAN=0, CAM=2), True, True, 2, 0., 0., False)
  assert [(addr, bus) for addr, _, bus in packets] == [(0x12A, 1), (0x110 if alt else 0x50, 0)]
  assert all(h.tx(make_CANPacket(addr, bus, data)) for addr, data, bus in packets)
  h.seed(button=4)
  assert all(not h.tx(make_CANPacket(addr, bus, data)) for addr, data, bus in packets)


def test_companion_rejection_does_not_reset_or_borrow_primary_rate_history(native):
  h = Hooks(native, 21, strict=False)
  h.engage()
  assert h.tx(h.steer(10))
  assert not h.tx(h.packed('LKAS', {'TORQUE_REQUEST': 20, 'STEER_REQ': 1}, 0))
  assert h.tx(h.steer(20))  # Its own previous value is still 10.
  assert h.tx(h.packed('LKAS', {'TORQUE_REQUEST': 10, 'STEER_REQ': 1}, 0))
  assert h.tx(h.packed('LKAS', {'TORQUE_REQUEST': 20, 'STEER_REQ': 1}, 0))


def test_dual_streams_cannot_pool_request_credit_and_valid_cuts_still_work(native):
  h = Hooks(native, 21, strict=False)
  h.engage()

  def pair(request):
    return (h.tx(h.steer(2, request)),
            h.tx(h.packed('LKAS', {'TORQUE_REQUEST': 2, 'STEER_REQ': request}, 0)))

  for _ in range(45):
    assert pair(1) == (True, True)
  assert pair(0) == (False, False)  # 90 combined frames still aren't 89 per channel.
  for n in range(89):
    h.now += 10_000
    h.lib.set_timer(h.now)
    if n % 20 == 0:
      h.seed()
    assert pair(1) == (True, True)
  assert pair(0) == (True, True)
  assert pair(0) == (True, True)
  assert pair(0) == (False, False)


@pytest.mark.parametrize('camera', [False, True])
def test_real_angle_host_keeps_inactive_companion_frames_without_torque_bypass(native, camera):
  h = Hooks(native, (29 if camera else 21) | 16384, strict=False)
  h.engage()
  flags = HyundaiFlags.CANFD_HDA2 | HyundaiFlags.ANGLE_CONTROL | (HyundaiFlags.CAMERA_SCC if camera else 0)
  cp = NS(flags=flags, openpilotLongitudinalControl=True)
  can = NS(ECAN=0 if camera else 1, ACAN=1 if camera else 0, CAM=2)
  if camera:
    packets = hyundaicanfd.create_steering_messages_camera_scc(
      1, h.packer, cp, can, NS(latActive=True), True, 0, NS(adrv_0x161=None, mdps=None, lfa={}, lfa_alt={}), 12.3, 50, True)
    assert [(addr, bus) for addr, _, bus in packets] == [(0xCB, 0), (0x12A, 0)]
  else:
    packets = hyundaicanfd.create_steering_messages(h.packer, cp, can, True, True, 0, 12.3, 50, True)
    assert [(addr, bus) for addr, _, bus in packets] == [(0x12A, 1), (0x50, 0)]
  assert all(h.tx(make_CANPacket(addr, bus, data)) for addr, data, bus in packets)
  assert not h.tx(h.steer(2))  # Angle mode cannot also command torque.
  h.seed(button=4)
  for addr, data, bus in packets:
    if camera and addr == 0x12A:
      assert h.tx(make_CANPacket(addr, bus, data))  # Disabled angle-mode sentinel only.
    else:
      assert not h.tx(make_CANPacket(addr, bus, data))


def test_torque_profiles_cannot_hide_angle_actuation_in_any_encoding(native):
  h = Hooks(native, strict=False)
  h.engage()
  assert not h.tx(h.packed('LFA_ALT', {'LKAS_ANGLE_ACTIVE': 2, 'LKAS_ANGLE_CMD': 12.3, 'LKAS_ANGLE_MAX_TORQUE': 50}))
  assert not h.tx(h.packed('LFA', {'TORQUE_REQUEST': 0, 'STEER_REQ': 0, 'LKAS_ANGLE_ACTIVE': 2,
                                 'LKAS_ANGLE_CMD': 12.3, 'LKAS_ANGLE_MAX_TORQUE': 50}))


def test_angle_queue_is_purged_on_cancel_and_strict_profile_cannot_enable_angle(native):
  h = Hooks(native, 29 | 16384, strict=False)
  h.engage()
  for _ in range(2):
    assert h.tx(h.packed('LFA_ALT', {'LKAS_ANGLE_ACTIVE': 2, 'LKAS_ANGLE_CMD': 12.3, 'LKAS_ANGLE_MAX_TORQUE': 50}))
  h.seed(button=4)
  assert h.lib.canfd_test_queue_count(0xCB, 0) == 0
  stock = h.packed('LFA_ALT', {'LKAS_ANGLE_ACTIVE': 1}, 2)
  expected = bytes(stock.data[0:24])
  assert h.forwarded(stock) == (0, 24, expected)
  strict = Hooks(native, 29 | 16384)
  strict.engage()
  assert not strict.tx(strict.packed('LFA', {'TORQUE_REQUEST': 0, 'STEER_REQ': 0, 'LKAS_ANGLE_ACTIVE': 2}))


@pytest.mark.parametrize('camera', [False, True])
def test_angle_actuation_cannot_use_an_unselected_encoder(native, camera):
  h = Hooks(native, (29 if camera else 21) | 16384, strict=False)
  h.engage()
  if camera:
    assert not h.tx(h.packed('LFA', {'TORQUE_REQUEST': 0, 'STEER_REQ': 0, 'LKAS_ANGLE_ACTIVE': 2,
                                   'LKAS_ANGLE_CMD': 12.3, 'LKAS_ANGLE_MAX_TORQUE': 50}, 0))
  else:
    assert not h.tx(h.packed('LFA_ALT', {'LKAS_ANGLE_ACTIVE': 2, 'LKAS_ANGLE_CMD': 12.3, 'LKAS_ANGLE_MAX_TORQUE': 50}, 0))
