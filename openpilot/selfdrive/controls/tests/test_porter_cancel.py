"""Run the production PCM publish block without IPC or vehicle hardware."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace as NS

from opendbc.car.hyundai.porter import (
  PorterLeadTracker, pcm_cruise_min_kph, porter_below_cruise_minimum, porter_navi_target_kph,
)


class Messages(dict):
  frame = 0


class TestPorterCancel:
  @classmethod
  def setup_class(cls):
    path = Path(__file__).resolve().parents[1] / 'controlsd.py'
    tree = ast.parse(path.read_text())
    publish = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'Controls'
                   for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'publish')
    pcm = next(n for n in publish.body if isinstance(n, ast.If) and ast.unparse(n.test) == 'self.CP.pcmCruise')
    cls.code = compile(ast.Module(body=[pcm], type_ignores=[]), str(path), 'exec')

  def run_target(self, planner=40, navigation=80, mode=0, lead=None, fingerprint='HYUNDAI_PORTER_II_EV',
                 enabled=True, cruise=True, x_state=0, resume=False):
    cc = NS(enabled=enabled, latActive=True, cruiseControl=NS(cancel=False, resume=resume))
    cs = NS(vCruiseCluster=80, vEgo=15, cruiseState=NS(enabled=cruise, speed=40 / 3.6))
    lead = lead or NS(status=False, dRel=0, vRel=0)
    sm = Messages(radarState=NS(leadOne=lead), selfdriveState=NS(personality=NS(raw=1)))
    control = NS(CP=NS(brand='hyundai', pcmCruise=True, carFingerprint=fingerprint),
                 params=NS(get_int=lambda key: mode), porter_lead_tracker=PorterLeadTracker(), sm=sm)
    hud = NS()
    env = {'self': control, 'CC': cc, 'CS': cs, 'hudControl': hud, 'desired_kph': navigation,
           'setSpeed': planner / 3.6, 'lp': NS(xState=x_state), 'DT_CTRL': .01,
           'CV': NS(MS_TO_KPH=3.6, KPH_TO_MS=1 / 3.6),
           'pcm_cruise_min_kph': pcm_cruise_min_kph, 'porter_navi_target_kph': porter_navi_target_kph,
           'porter_below_cruise_minimum': porter_below_cruise_minimum}
    exec(self.code, env)
    return cc, hud

  def test_planner_below_minimum_cancels_without_disabling_lateral(self):
    for target in (0, 10, 29.9):
      cc, hud = self.run_target(planner=target)
      assert cc.cruiseControl.cancel
      assert not cc.cruiseControl.resume
      assert cc.latActive
      assert abs(hud.setSpeed * 3.6 - 30) < 1e-5

  def test_navigation_below_minimum_cancels(self):
    assert self.run_target(navigation=20)[0].cruiseControl.cancel

  def test_cancellation_clears_an_existing_resume_request(self):
    cc, _ = self.run_target(planner=0, resume=True)
    assert cc.cruiseControl.cancel
    assert not cc.cruiseControl.resume

  def test_ten_kph_closing_lead_cancels_before_floor_is_applied(self):
    lead = NS(status=True, dRel=20, vRel=10 / 3.6 - 15)
    assert self.run_target(lead=lead)[0].cruiseControl.cancel

  def test_threshold_and_invalid_targets(self):
    for target in (30, 30.1, 40, 8.333333015441895 * 3.6, math.nan, math.inf):
      assert not porter_below_cruise_minimum(target)
    for target in (30, 30.1):
      assert not self.run_target(planner=target)[0].cruiseControl.cancel

  def test_mode_specific_unclamped_target(self):
    assert self.run_target(mode=2, navigation=10)[0].cruiseControl.cancel
    assert not self.run_target(mode=2, planner=10)[0].cruiseControl.cancel
    assert self.run_target(mode=3, planner=10, x_state=3)[0].cruiseControl.cancel
    assert not self.run_target(mode=3, planner=10, x_state=0)[0].cruiseControl.cancel

  def test_scope_and_no_automatic_reengagement(self):
    for kwargs in ({'fingerprint': 'OTHER'}, {'enabled': False}, {'cruise': False}, {'mode': 1}):
      cc, _ = self.run_target(planner=10, **kwargs)
      assert not cc.cruiseControl.cancel
      assert not cc.cruiseControl.resume
    cc, _ = self.run_target(planner=40, cruise=False)
    assert not cc.cruiseControl.resume
