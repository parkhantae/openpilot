"""Production PCM publish and stateful cancellation regressions, without hardware."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from opendbc.car.hyundai.porter import (
  PorterCruiseButtons, PorterLeadTracker, PorterLowSpeedCancel, pcm_cruise_min_kph,
  porter_lead_target_kph, porter_navi_target_kph,
)


def pcm_code(source):
  tree = ast.parse(source)
  publish = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'Controls'
                 for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'publish')
  node = next(n for n in publish.body if isinstance(n, ast.If) and ast.unparse(n.test) == 'self.CP.pcmCruise')
  return compile(ast.Module(body=[node], type_ignores=[]), 'actual_pcm_publish', 'exec')


class Messages(dict):
  frame = 0

  def all_checks(self, services):
    return all(self.fresh[name] for name in services)


class Harness:
  def __init__(self, code=None):
    path = Path(__file__).resolve().parents[1] / 'controlsd.py'
    self.code = code or pcm_code(path.read_text())
    self.mode = 0
    self.cs = NS(vCruiseCluster=80, vEgo=15, canValid=True, gasPressed=False, brakePressed=False,
                 buttonEvents=[], cruiseState=NS(enabled=True, speed=40 / 3.6))
    self.lead = NS(status=False, dRel=0, vRel=0)
    self.lp = NS(speeds=[40 / 3.6] * 33, xState=0)
    self.sm = Messages(radarState=NS(leadOne=self.lead), longitudinalPlan=self.lp,
                       selfdriveState=NS(personality=NS(raw=1)))
    self.sm.fresh = dict.fromkeys(('carState', 'radarState', 'longitudinalPlan'), True)
    self.control = NS(CP=NS(brand='hyundai', pcmCruise=True, carFingerprint='HYUNDAI_PORTER_II_EV'),
                      params=NS(get_int=lambda key: self.mode), sm=self.sm,
                      porter_lead_tracker=PorterLeadTracker(), porter_low_speed_cancel=PorterLowSpeedCancel())
    self.enabled = True
    self.navigation = None

  def step(self, now):
    self.sm.frame = round(now * 100)
    cc = NS(enabled=self.enabled, latActive=True, cruiseControl=NS(cancel=False, resume=False))
    hud = NS()
    desired = min(80, self.navigation) if self.navigation is not None else 80
    env = {'self': self.control, 'CS': self.cs, 'CC': cc, 'hudControl': hud, 'lp': self.lp,
           'speeds': self.lp.speeds, 'setSpeed': self.lp.speeds[-1] if self.lp.speeds else desired / 3.6,
           'desired_kph': desired, 'carrot_man': NS() if self.navigation is not None else None,
           'CV': NS(MS_TO_KPH=3.6, KPH_TO_MS=1 / 3.6), 'DT_CTRL': .01, 'math': math,
           'cloudlog': NS(info=lambda *args: None), 'pcm_cruise_min_kph': pcm_cruise_min_kph,
           'porter_navi_target_kph': porter_navi_target_kph, 'porter_lead_target_kph': porter_lead_target_kph}
    exec(self.code, env)
    return cc, hud.setSpeed


@pytest.mark.parametrize('source', ['planner', 'navigation', 'lead'])
def test_continuous_low_target_cancels_after_confirmation(source):
  h = Harness()
  if source == 'planner':
    h.lp.speeds = [10 / 3.6] * 33
  elif source == 'navigation':
    h.navigation = 10
  else:
    h.lead.status, h.lead.dRel, h.lead.vRel = True, 20, 10 / 3.6 - h.cs.vEgo
  for i in range(30):
    assert not h.step(i * .01)[0].cruiseControl.cancel
  cc, _ = h.step(.3)
  assert cc.cruiseControl.cancel and not cc.cruiseControl.resume and cc.latActive


def test_transient_zero_does_not_cancel_or_poison_normal_speed_control():
  h = Harness()
  h.lp.speeds = [0] * 33
  h.step(0)
  assert not h.step(.29)[0].cruiseControl.cancel
  h.lp.speeds = [50 / 3.6] * 33
  for i in range(30, 151):
    cc, target = h.step(i * .01)
    assert not cc.cruiseControl.cancel and target * 3.6 == pytest.approx(50)
  h.lp.speeds = [0] * 33
  assert not h.step(1.51)[0].cruiseControl.cancel


@pytest.mark.parametrize('target', [0, 29.9])
def test_valid_stop_and_just_below_minimum_targets_cancel(target):
  h = Harness()
  h.lp.speeds = [target / 3.6] * 33
  assert not h.step(0)[0].cruiseControl.cancel
  assert h.step(.3)[0].cruiseControl.cancel


def test_confirmed_cancellation_stays_requested_until_oem_switches_off():
  h = Harness()
  h.lp.speeds = [0] * 33
  h.step(0)
  assert h.step(.3)[0].cruiseControl.cancel
  h.lp.speeds = [50 / 3.6] * 33
  assert h.step(.4)[0].cruiseControl.cancel
  h.cs.cruiseState.enabled = False
  assert not h.step(.5)[0].cruiseControl.cancel
  assert not h.step(2)[0].cruiseControl.resume


@pytest.mark.parametrize('target', [30, 30.1, 8.333333015441895 * 3.6])
def test_minimum_boundary_does_not_cancel(target):
  h = Harness()
  h.lp.speeds = [target / 3.6] * 33
  for t in (0, .3, 1):
    assert not h.step(t)[0].cruiseControl.cancel


def test_stale_and_invalid_plans_cannot_trigger_cancel():
  for speeds, fresh in (([], True), ([math.nan], True), ([-1], True), ([0], False)):
    h = Harness()
    h.lp.speeds, h.sm.fresh['longitudinalPlan'] = speeds, fresh
    for t in (0, .3, 1):
      assert not h.step(t)[0].cruiseControl.cancel


def test_stale_lead_cannot_trigger_cancel():
  h = Harness()
  h.lead.status, h.lead.dRel, h.lead.vRel = True, 20, -15
  h.sm.fresh['radarState'] = False
  for t in (0, .3, 1):
    assert not h.step(t)[0].cruiseControl.cancel


@pytest.mark.parametrize('inhibit', ['gasPressed', 'brakePressed', 'canValid', 'manual', 'disabled', 'stock_off', 'pcm1'])
def test_driver_and_validity_gates_clear_confirmation(inhibit):
  h = Harness()
  h.lp.speeds = [10 / 3.6] * 33
  h.step(0)
  if inhibit in ('gasPressed', 'brakePressed'):
    setattr(h.cs, inhibit, True)
  elif inhibit == 'canValid':
    h.cs.canValid = False
  elif inhibit == 'manual':
    h.cs.buttonEvents = [NS(pressed=True)]
  elif inhibit == 'disabled':
    h.enabled = False
  elif inhibit == 'stock_off':
    h.cs.cruiseState.enabled = False
  else:
    h.mode = 1
  assert not h.step(.3)[0].cruiseControl.cancel


def test_cancel_acknowledgement_then_manual_reengagement_restores_buttons():
  h = Harness()
  pulses = PorterCruiseButtons()
  h.lp.speeds = [10 / 3.6] * 33
  h.step(0)
  cc, target = h.step(.3)
  assert pulses.update(.3, target * 3.6, 40, 1, enabled=True, cancel=cc.cruiseControl.cancel) == 4
  h.cs.cruiseState.enabled = False
  h.lp.speeds = [50 / 3.6] * 33
  cc, target = h.step(.4)
  assert not cc.cruiseControl.cancel and not cc.cruiseControl.resume
  assert pulses.update(.4, target * 3.6, 0, 2, enabled=False) is None
  h.cs.buttonEvents = [NS(pressed=True)]  # driver, never an automatic RES
  h.cs.cruiseState.enabled = True
  cc, target = h.step(1)
  assert not cc.cruiseControl.cancel
  assert pulses.update(1, target * 3.6, 40, 3, enabled=True, manual=True) is None
  h.cs.buttonEvents = []
  cc, target = h.step(1.4)
  assert not cc.cruiseControl.cancel
  assert pulses.update(1.4, target * 3.6, 40, 4, enabled=True) == 1
  h.lp.speeds = [35 / 3.6] * 33
  h.step(2)
  assert not h.step(2.5)[0].cruiseControl.cancel


def test_above_minimum_targets_remain_unchanged_over_time():
  h = Harness()
  for i in range(400):
    planner = (50, 35, 70, 30)[(i // 50) % 4]
    h.lp.speeds = [planner / 3.6] * 33
    h.lead.status, h.lead.dRel, h.lead.vRel = i % 80 < 40, 40, -2
    cc, target = h.step(i * .01)
    # Golden results captured from the known-good 1fff5768 publish block.
    assert target * 3.6 == pytest.approx((40, 35, 40, 30)[(i // 50) % 4])
    assert not cc.cruiseControl.cancel


def test_clock_fault_resets_confirmation():
  policy = PorterLowSpeedCancel()
  assert not policy.update(1, 10, eligible=True, cruise_enabled=True)
  assert not policy.update(.9, 10, eligible=True, cruise_enabled=True)
  assert not policy.update(1, 10, eligible=True, cruise_enabled=True)
  assert policy.update(1.3, 10, eligible=True, cruise_enabled=True)
