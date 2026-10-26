"""Synthetic tests only. Constants below are test fixtures, not vehicle tuning."""
import unittest
from dataclasses import replace
from porter_cruise_logic import ButtonDecider, State


class TestDecider(unittest.TestCase):
    def setUp(self):
        self.c = ButtonDecider(minimum=30, maximum=100, interval=0.5,
                               ack_timeout=2.0, max_age=0.2)
        self.s = State(True, True, True, False, False, False, False,
                       False, True, 0.0, 60.0)

    def step(self, t, target=70, **changes):
        return self.c.update(t, target, replace(self.s, received_at=t, **changes))

    def test_up_ack_and_rate_limit(self):
        self.assertEqual(self.step(0), "RES_ACCEL")
        self.assertIsNone(self.step(0.1))  # unchanged OEM setting
        self.assertIsNone(self.step(0.2, set_speed=61))  # ack, interval not elapsed
        self.assertEqual(self.step(0.5, set_speed=61), "RES_ACCEL")

    def test_down_and_target_reached(self):
        self.assertEqual(self.step(0, 50), "SET_DECEL")
        self.assertIsNone(self.step(0.5, 50, set_speed=50))

    def test_interlocks(self):
        for key, value in (("brake", True), ("gas", True), ("manual_button", True),
                           ("fault", True), ("standstill", True), ("drive", False),
                           ("cruise_enabled", False), ("valid", False)):
            with self.subTest(key=key):
                self.setUp()
                self.assertIsNone(self.step(0, **{key: value}))
                self.assertIsNone(self.step(1))  # intervention remains latched

    def test_no_feedback_timeout_and_explicit_rearm(self):
        self.step(0)
        self.assertIsNone(self.step(2))
        self.assertTrue(self.c.blocked)
        self.assertIsNone(self.step(3, set_speed=61))
        self.step(4, enabled=False)
        self.assertEqual(self.step(4.5), "RES_ACCEL")

    def test_stale_or_future_input(self):
        for received in (-1.0, 1.0):
            self.setUp()
            self.assertIsNone(self.c.update(0, 70, replace(self.s, received_at=received)))

    def test_invalid_target_or_setting(self):
        for target in (float("nan"), float("inf"), 0, 101):
            self.setUp()
            self.assertIsNone(self.step(0, target))
        self.setUp()
        self.assertIsNone(self.step(0, set_speed=0))

    def test_wrong_direction_ack(self):
        self.step(0)
        self.assertIsNone(self.step(0.5, set_speed=59))
        self.assertTrue(self.c.blocked)

    def test_old_feedback_cannot_ack(self):
        self.step(0)
        self.assertIsNone(self.c.update(0.1, 70, replace(self.s, set_speed=61)))
        self.assertIsNotNone(self.c.pending)

    def test_clock_reversal(self):
        self.step(1)
        self.assertIsNone(self.step(0.9))
        self.assertTrue(self.c.blocked)


if __name__ == "__main__":
    unittest.main()
