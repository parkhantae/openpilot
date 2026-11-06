"""Dispatch freshness must include host processing, with a matched clock domain."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from opendbc.car.hyundai import porter_main_set as main_set


class TestPorterCanClock(unittest.TestCase):
  def test_live_uses_can_boottime_not_apply_monotonic_even_after_suspend(self):
    calls = []
    clock = NS(CLOCK_BOOTTIME=7, CLOCK_MONOTONIC=1,
               clock_gettime_ns=lambda which: calls.append(which) or 9_000_000_000)
    with patch.object(main_set, 'os', NS(environ={})), patch.object(main_set, 'time', clock):
      self.assertEqual(main_set.porter_can_clock_nanos(1_000_000_000), 9_000_000_000)
    self.assertEqual(calls, [7])

  def test_replay_uses_supplied_timestamp_without_reading_live_clock(self):
    clock = NS(clock_gettime_ns=lambda _: self.fail('replay read the live clock'))
    with patch.object(main_set, 'os', NS(environ={'REPLAY': ''})), patch.object(main_set, 'time', clock):
      self.assertEqual(main_set.porter_can_clock_nanos(42), 42)

  def test_platform_without_boottime_uses_monotonic(self):
    clock = NS(monotonic_ns=lambda: 100)
    with patch.object(main_set, 'os', NS(environ={})), patch.object(main_set, 'time', clock):
      self.assertEqual(main_set.porter_can_clock_nanos(9), 100)

  def test_actual_production_call_supplies_apply_time_only_for_porter(self):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'carcontroller.py').read_text())
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and
                isinstance(n.func, ast.Attribute) and n.func.attr == 'create_button_messages' and
                any(kw.arg == 'apply_now_nanos' for kw in n.keywords))
    code = compile(ast.Expression(body=call), 'actual_porter_dispatch_clock_call', 'eval')
    for fingerprint, expected in (('porter', 1000), ('other', None)):
      captured = []
      obj = NS(CP=NS(carFingerprint=fingerprint),
               create_button_messages=lambda *a,result=captured,**kw: result.append(kw))
      eval(code, dict(self=obj, CAR=NS(HYUNDAI_PORTER_II_EV='porter'), CC=None, CS=None,
                      now_nanos=1000))
      self.assertEqual(captured[0]['apply_now_nanos'], expected)
