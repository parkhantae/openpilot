"""Offline-only tests for driver-authorized immediate Porter SET.

This module never opens CAN devices or sends frames to a vehicle.
"""
import ast
from pathlib import Path
import unittest

from opendbc.car.hyundai.porter_main_set import PorterMainSet


class TestPorterPedalReleaseOnly(unittest.TestCase):
  @staticmethod
  def tick(state, tick, *, main_pressed=False, gas_pressed=False,
           request=True, blocked=False, stock_enabled=False,
           manual_button=0, configured=True):
    return state.update(
      tick * .01, tick // 2,
      main_pressed=main_pressed, manual_button=manual_button,
      blocked=blocked, request=request, stock_enabled=stock_enabled,
      configured=configured, gas_pressed=gas_pressed, pedal_only=True)

  def arm(self, state):
    self.assertIsNone(self.tick(state, 0, main_pressed=True))
    self.assertIsNone(self.tick(state, 1, main_pressed=True))
    self.assertIsNone(self.tick(state, 2))

  def test_actual_controller_always_requires_pedal_cue(self):
    controller = Path(__file__).resolve().parents[1] / "carcontroller.py"
    tree = ast.parse(controller.read_text(encoding="utf-8"))
    calls = [
      node for node in ast.walk(tree)
      if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
      and node.func.attr == "update" and isinstance(node.func.value, ast.Attribute)
      and node.func.value.attr == "porter_main_set"
    ]
    self.assertEqual(len(calls), 1)
    keywords = {kw.arg: kw.value for kw in calls[0].keywords}
    self.assertIsInstance(keywords["pedal_only"], ast.Constant)
    self.assertIs(keywords["pedal_only"].value, True)

  def test_no_automatic_set_from_elapsed_time_without_pedal(self):
    for two_press in (False, True):
      with self.subTest(two_press=two_press):
        state = PorterMainSet(two_press=two_press, single_press=True)
        self.arm(state)
        for tick in range(3, 220):
          self.assertIsNone(self.tick(state, tick))
        self.assertEqual(state.requests, 0)

  def test_first_fresh_sample_on_qualified_release_starts_set(self):
    for two_press in (False, True):
      with self.subTest(two_press=two_press):
        state = PorterMainSet(two_press=two_press, single_press=True)
        self.arm(state)
        for tick in range(3, 100):
          self.assertIsNone(self.tick(state, tick, gas_pressed=tick >= 20,
                                      request=tick < 20))
        self.assertEqual(self.tick(state, 100), 2)
        self.assertEqual(state.requests, 1)

  def test_release_with_missing_request_is_not_queued(self):
    state = PorterMainSet(two_press=True, single_press=True)
    self.arm(state)
    for tick in range(3, 100):
      self.tick(state, tick, gas_pressed=tick >= 20, request=tick < 20)
    for tick in range(100, 120):
      self.assertIsNone(self.tick(state, tick, request=False))
    for tick in range(120, 220):
      self.assertIsNone(self.tick(state, tick))
    self.assertEqual(state.requests, 0)

  def test_brake_or_manual_button_cannot_issue_set_on_release(self):
    for override in ({"blocked": True}, {"manual_button": 4}, {"configured": False}):
      with self.subTest(override=override):
        state = PorterMainSet(two_press=True, single_press=True)
        self.arm(state)
        for tick in range(3, 100):
          self.tick(state, tick, gas_pressed=tick >= 20, request=tick < 20)
        self.assertIsNone(self.tick(state, 100, **override))
        for tick in range(101, 190):
          self.assertIsNone(self.tick(state, tick))
        self.assertEqual(state.requests, 0)

  def test_stock_already_active_does_not_issue_new_set(self):
    state = PorterMainSet(two_press=True, single_press=True)
    self.arm(state)
    for tick in range(3, 100):
      self.tick(state, tick, gas_pressed=tick >= 20, request=tick < 20)
    self.assertIsNone(self.tick(state, 100, stock_enabled=True))
    self.assertEqual(state.requests, 0)


if __name__ == "__main__":
  unittest.main()
