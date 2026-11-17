"""Pure offline regression coverage for Porter Test3 (no CAN hardware)."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "porter.py"
spec = importlib.util.spec_from_file_location("porter_retry_budget", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestPorterRetryBudget(unittest.TestCase):
  def exercise(self, budget, ticks=700):
    b = module.PorterCruiseButtons()
    for tick in range(ticks):
      b.update(tick * .01, 55, 50, tick // 2, enabled=True,
               press_seconds=.04, gap_seconds=.3, retry_limit=budget)
    return b

  def test_zero_blocks_after_first_unanswered_request(self):
    b = self.exercise(0)
    self.assertEqual((b.requests, b.timeouts), (1, 1))
    self.assertTrue(b.retry_exhausted)

  def test_two_allows_two_extra_requests_then_blocks(self):
    b = self.exercise(2)
    self.assertEqual((b.requests, b.timeouts), (3, 3))
    self.assertTrue(b.retry_exhausted)

  def test_large_test3_is_clamped(self):
    b = self.exercise(20)
    self.assertEqual(b.requests, 3)

  def test_disabled_clears_budget(self):
    b = self.exercise(0)
    self.assertIsNone(b.update(7.0, 55, 50, 351, enabled=False, retry_limit=0))
    self.assertFalse(b.retry_exhausted)

  def test_manual_clears_budget(self):
    b = self.exercise(0)
    self.assertIsNone(b.update(7.0, 55, 50, 351, enabled=True, manual=True, retry_limit=0))
    self.assertFalse(b.retry_exhausted)

  def test_ack_resets_counter(self):
    b = module.PorterCruiseButtons()
    self.assertEqual(b.update(0, 55, 50, 0, enabled=True, retry_limit=2), 1)
    b.update(.02, 55, 51, 1, enabled=True, retry_limit=2)
    self.assertEqual((b.acks, b.retry_attempts), (1, 0))

  def test_legacy_without_retry_limit_unchanged(self):
    b = self.exercise(None)
    self.assertGreater(b.requests, 3)


if __name__ == "__main__":
  unittest.main()
