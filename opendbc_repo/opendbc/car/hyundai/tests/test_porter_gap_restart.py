"""New stock-cruise sessions must not inherit the preceding GAP speed cap."""

import ast
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from opendbc.car.hyundai.porter import PorterLeadTracker


def observe_from_controlsd(tracker, enabled, *, valid=True, timeout=False, fault=False, fresh=True, name="HYUNDAI_PORTER_II_EV", pcm=True, direct_long=False):
  source = Path(__file__).resolve().parents[5] / "openpilot/selfdrive/controls/controlsd.py"
  tree = ast.parse(source.read_text())
  nodes = [
    n
    for n in ast.walk(tree)
    if isinstance(n, ast.If) and "self.porter_lead_tracker.observe_stock_cruise(" in ast.unparse(n) and "self.CP.carFingerprint" in ast.unparse(n.test)
  ]
  assert len(nodes) == 1
  obj = NS(CP=NS(carFingerprint=name, pcmCruise=pcm, openpilotLongitudinalControl=direct_long), sm=NS(all_checks=lambda _: fresh), porter_lead_tracker=tracker)
  cs = NS(cruiseState=NS(enabled=enabled), canValid=valid, canTimeout=timeout, accFaulted=fault)
  exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), {"self": obj, "CS": cs})


def update(p, now, *, target=41.0, stock=39.0, distance=0.0, relative=0.0, visible=False, adaptive=True):
  return p.update(now, target, stock, 37.4 / 3.6, distance, relative, 2, lead_visible=visible, gap_time_s=1.175, reaction_s=6.5, adaptive=adaptive)


def preceding_low_cap():
  p = PorterLeadTracker()
  observe_from_controlsd(p, True)
  assert update(p, 0, target=30) == 30
  return p


def test_log90_restart_uses_current_39_instead_of_preceding_30():
  p = preceding_low_cap()
  # No tracker updates during the 53-second stock-OFF interval, just as in
  # production. Observe OFF outside the active button-control branch.
  observe_from_controlsd(p, False)
  observe_from_controlsd(p, True)
  assert update(p, 53.32, target=40.994629, stock=39) == 39
  assert not p.recovery_ready


@pytest.mark.parametrize("reason", ["invalid_can", "timeout", "fault", "stale"])
def test_invalid_off_sample_cannot_erase_in_drive_protection(reason):
  p = preceding_low_cap()
  kw = {"valid": reason != "invalid_can", "timeout": reason == "timeout", "fault": reason == "fault", "fresh": reason != "stale"}
  observe_from_controlsd(p, False, **kw)
  observe_from_controlsd(p, True)
  assert update(p, 53.32) == 30
  assert not p.recovery_ready


def test_continuously_enabled_clock_gap_retains_low_cap():
  p = preceding_low_cap()
  observe_from_controlsd(p, True)
  assert update(p, 53.32) == 30


@pytest.mark.parametrize(
  "target,distance,relative,visible,expected",
  [
    (32.0, 0.0, 0.0, False, 32.0),
    (41.0, 5.0, -8.0, True, 30.0),
  ],
)
def test_restart_still_applies_current_navigation_and_close_lead_constraints(target, distance, relative, visible, expected):
  p = preceding_low_cap()
  observe_from_controlsd(p, False)
  observe_from_controlsd(p, True)
  assert update(p, 53.32, target=target, distance=distance, relative=relative, visible=visible) == expected


def test_repeated_enabled_samples_do_not_restart_recovery_each_frame():
  p = preceding_low_cap()
  observe_from_controlsd(p, False)
  observe_from_controlsd(p, True)
  assert update(p, 53.32) == 39
  values = []
  for n in range(1, 101):
    p.observe_stock_cruise(True, valid=True)
    values.append(update(p, 53.32 + n * 0.01))
  assert 39 < values[-1] < 41
  assert max(b - a for a, b in zip(values, values[1:], strict=False)) <= 0.018 + 1e-8


def test_gap_mode_switch_keeps_the_observed_stock_state():
  p = preceding_low_cap()
  assert p.stock_enabled is True
  update(p, 0.01, adaptive=False)
  assert p.stock_enabled is True
  update(p, 0.02, adaptive=True)
  assert p.stock_enabled is True
  p.observe_stock_cruise(False, valid=True)
  p.observe_stock_cruise(True, valid=True)
  assert update(p, 53.32) == 39


@pytest.mark.parametrize(
  "name,pcm,direct_long", [("HYUNDAI_IONIQ_5", True, False), ("HYUNDAI_PORTER_II_EV", False, True), ("HYUNDAI_PORTER_II_EV", True, True)]
)
def test_publisher_observation_is_scoped_to_porter_conventional_cruise(name, pcm, direct_long):
  p = preceding_low_cap()
  observe_from_controlsd(p, False, name=name, pcm=pcm, direct_long=direct_long)
  observe_from_controlsd(p, True)
  assert update(p, 53.32) == 30
