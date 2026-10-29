import unittest
from types import SimpleNamespace as NS

from opendbc.car.hyundai.porter import porter_auto_set_speed_valid


class TestPorterSetSpeed(unittest.TestCase):
  def valid(self, cluster=31.5, fl=29., rr=29., profile=60417):
    cp = NS(safetyConfigs=[NS(safetyParam=profile)])
    cs = NS(vEgo=fl/3.6, vEgoCluster=cluster/3.6, wheelSpeeds=NS(fl=fl/3.6, rr=rr/3.6))
    return porter_auto_set_speed_valid(cp, cs)

  def test_log552_dashboard_release_is_above_factory_threshold(self):
    self.assertTrue(self.valid())
    self.assertTrue(self.valid(cluster=31.375, fl=29.469, rr=29.469))
    self.assertTrue(self.valid(cluster=30.75, fl=26.758, rr=26.758))
    for old in (9217, 25601, 58369):
      self.assertFalse(self.valid(profile=old))

  def test_cluster_and_both_wheels_must_be_plausible(self):
    for args in (dict(cluster=29.875), dict(cluster=160.125), dict(fl=24.96875),
                 dict(rr=24.96875), dict(fl=25.), dict(rr=25.), dict(fl=161.),
                 dict(cluster=float('nan')), dict(fl=float('inf')), dict(rr=float('nan'))):
      self.assertFalse(self.valid(**args), args)
    self.assertTrue(self.valid(cluster=30, fl=25, rr=25))
    self.assertTrue(self.valid(cluster=160, fl=160, rr=155))

  def test_missing_cluster_or_wheel_inputs_cannot_authorize_new_profile(self):
    cp = NS(safetyConfigs=[NS(safetyParam=60417)])
    self.assertFalse(porter_auto_set_speed_valid(cp, NS(vEgo=40/3.6)))
    self.assertFalse(porter_auto_set_speed_valid(cp, NS(vEgo=40/3.6, vEgoCluster=42/3.6)))
