from types import SimpleNamespace as NS
import unittest

from opendbc.car import apply_driver_steer_torque_limits
from opendbc.car.hyundai.porter_steering import apply_porter_steer_torque_limits


def steering_limits(down=5):
  return NS(STEER_MAX=409, STEER_DELTA_UP=3, STEER_DELTA_DOWN=down,
            STEER_DRIVER_ALLOWANCE=50, STEER_DRIVER_FACTOR=1, STEER_DRIVER_MULTIPLIER=2)


class TestPorterSteering(unittest.TestCase):
  def test_recorded_countersteer_retreats_at_native_required_rate(self):
    for sign in (-1, 1):
      with self.subTest(sign=sign):
        result = apply_porter_steer_torque_limits(sign * 409, sign * 339, -sign * 207, steering_limits())
        self.assertEqual(result, sign * 329)

  def test_nominal_torque_and_configured_unwind_are_unchanged(self):
    for down in (1, 4, 5, 7, 10, 20):
      for last in (-409, -200, -1, 0, 1, 200, 409):
        for target in (-409, -10, 0, 10, 409):
          with self.subTest(down=down, last=last, target=target):
            limits = steering_limits(down)
            self.assertEqual(apply_porter_steer_torque_limits(target, last, 0, limits),
                             apply_driver_steer_torque_limits(target, last, 0, limits))

  def test_driver_release_never_adds_torque_in_the_original_direction(self):
    for sign in (-1, 1):
      for last, driver in ((1, 500), (9, 500), (10, 300), (50, 300), (200, 207), (339, 207), (409, 150), (409, 51)):
        result = apply_porter_steer_torque_limits(sign * 409, sign * last, -sign * driver, steering_limits())
        self.assertLessEqual(abs(result), last)
        self.assertGreaterEqual(sign * result, 0)

  def test_existing_faster_retreat_and_zero_crossing_are_preserved(self):
    for sign in (-1, 1):
      limits = steering_limits(20)
      self.assertEqual(apply_porter_steer_torque_limits(sign * 409, sign * 339, -sign * 207, limits), sign * 319)
      self.assertEqual(apply_porter_steer_torque_limits(-sign * 409, sign * 5, -sign * 500, limits), -sign * 3)

  def test_host_only_driver_limit_keeps_configured_release_rate(self):
    for sign in (-1, 1):
      self.assertEqual(apply_porter_steer_torque_limits(sign * 409, sign * 339, -sign * 100, steering_limits()), sign * 334)
