import unittest
from types import SimpleNamespace

from opendbc.car.hyundai.porter import PORTER_GAP_TIME_S, PorterLeadTracker, porter_gap_time_s, porter_lead_target_kph
from opendbc.car.hyundai.porter_cancel import porter_cancel_target


class TestPorterGap(unittest.TestCase):
  def test_defaults_and_invalid_storage(self):
    for i, default in enumerate(PORTER_GAP_TIME_S, 1):
      for value in (0, 99, 301, 'bad'):
        def read(key, i=i, value=value):
          self.assertEqual(key, f'PorterGap{i}')
          return int(value)
        self.assertEqual(porter_gap_time_s(SimpleNamespace(get_int=read), i), default)

  def test_live_selected_gap(self):
    values = dict(PorterGap1=100, PorterGap2=130, PorterGap3=160, PorterGap4=200)
    params = SimpleNamespace(get_int=lambda key: values[key])
    self.assertEqual(porter_gap_time_s(params, 2), 1.3)
    values['PorterGap2'] = 250
    self.assertEqual(porter_gap_time_s(params, 2), 2.5)
    self.assertEqual(porter_gap_time_s(params, 1), 1.)

  def test_threshold_changes_tracker_and_cancel_together(self):
    # At 36 km/h with a 30 m lead closing at 1 m/s, projected distance is 22 m.
    # 1s => 15 m threshold; 2s => 25 m threshold.
    for time_s, expected in ((1., 60), (2., 32.4)):
      self.assertAlmostEqual(porter_lead_target_kph(60, 10, 30, -1, 1, gap_time_s=time_s), expected)
      tracker = PorterLeadTracker()
      self.assertAlmostEqual(tracker.update(0, 60, 60, 10, 30, -1, 1, gap_time_s=time_s), expected)
    for time_s, expected in ((1., 60), (2., 25.2)):
      # Lead 25.2 km/h, projected 24m: only the longer configured gap constrains.
      target = porter_cancel_target(60, 60, None, 10, 48, -3, 1, lead_visible=True, gap_time_s=time_s)
      self.assertAlmostEqual(target, expected)

  def test_explicit_defaults_preserve_existing_targets(self):
    for level, time_s in enumerate(PORTER_GAP_TIME_S, 1):
      for distance in (5, 20, 40, 80):
        for relative in (-5, -1, 0, 1):
          args = (70, 15, distance, relative, level)
          self.assertEqual(porter_lead_target_kph(*args), porter_lead_target_kph(*args, gap_time_s=time_s))
