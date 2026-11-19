"""Real schema and production publisher/event wiring; no live IPC."""

import ast
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from openpilot.cereal import car, log
from openpilot.selfdrive.car.porter_button_status import porter_button_unavailable, warn_porter_button_unavailable
from openpilot.selfdrive.selfdrived.events import EVENTS, ET
from opendbc.car.hyundai.porter import PorterCruiseButtons

ROOT = Path(__file__).resolve().parents[4]


def cp():
  return car.CarParams.new_message(
    brand='hyundai', carFingerprint='HYUNDAI_PORTER_II_EV', pcmCruise=True, safetyConfigs=[{'safetyModel': 'hyundai', 'safetyParam': 15489}]
  )


def state():
  return car.CarState.new_message(canValid=True, cruiseState={'enabled': True})


def publish(CP, CS, buttons):
  source = ROOT / 'openpilot/selfdrive/car/card.py'
  tree = ast.parse(source.read_text())
  node = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == 'co_send.carOutput.porterButtonUnavailable')
  output = log.Event.new_message()
  output.init('carOutput')
  obj = NS(CP=CP, CI=NS(CC=NS(porter_buttons=buttons)))
  exec(
    compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'),
    {'self': obj, 'CS': CS, 'co_send': output, 'porter_button_unavailable': porter_button_unavailable},
  )
  with log.Event.from_bytes(output.to_bytes()) as decoded:
    return decoded.carOutput.as_builder()


def event(CP, CS, output, fresh=True):
  source = ROOT / 'openpilot/selfdrive/selfdrived/selfdrived.py'
  tree = ast.parse(source.read_text())
  node = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and 'warn_porter_button_unavailable(' in ast.unparse(n.test))

  class SM(dict):
    def all_checks(self, _):
      return fresh

  found = []
  obj = NS(CP=CP, sm=SM(carOutput=output), events=NS(add=found.append))
  exec(
    compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'),
    {'self': obj, 'CS': CS, 'warn_porter_button_unavailable': warn_porter_button_unavailable, 'EventName': log.OnroadEvent.EventName},
  )
  return found


def test_unavailable_status_round_trips_through_actual_card_and_event_wiring():
  CP, CS = cp(), state()
  b = PorterCruiseButtons()
  assert event(CP, CS, publish(CP, CS, b)) == []
  b.retry_exhausted = True
  assert event(CP, CS, publish(CP, CS, b)) == [log.OnroadEvent.EventName.porterButtonUnavailable]
  b.retry_exhausted = False
  b.decel_only = True
  assert event(CP, CS, publish(CP, CS, b)) == [log.OnroadEvent.EventName.porterButtonUnavailable]
  b.decel_only = False
  assert event(CP, CS, publish(CP, CS, b)) == []


@pytest.mark.parametrize('reason', ['other_car', 'direct_long', 'non_pcm', 'stock_off', 'invalid_can', 'timeout', 'acc_fault', 'stale'])
def test_no_stale_or_other_vehicle_warning(reason):
  CP, CS = cp(), state()
  b = PorterCruiseButtons()
  b.retry_exhausted = True
  if reason == 'other_car':
    CP.carFingerprint = 'HYUNDAI_IONIQ_5'
  if reason == 'direct_long':
    CP.openpilotLongitudinalControl = True
  if reason == 'non_pcm':
    CP.pcmCruise = False
  if reason == 'stock_off':
    CS.cruiseState.enabled = False
  if reason == 'invalid_can':
    CS.canValid = False
  if reason == 'timeout':
    CS.canTimeout = True
  if reason == 'acc_fault':
    CS.accFaulted = True
  assert event(CP, CS, publish(CP, CS, b), fresh=reason != 'stale') == []


def test_warning_has_no_control_disable_override_or_actuation_side_effect():
  entry = EVENTS[log.OnroadEvent.EventName.porterButtonUnavailable]
  assert set(entry) == {ET.PERMANENT}
  assert 'Take Control' in entry[ET.PERMANENT].alert_text_2


@pytest.mark.parametrize('language', ['en', 'ko', 'zh-CHS'])
def test_new_warning_is_translated_and_fits_the_mid_alert(language):
  from PIL import ImageFont
  from openpilot.selfdrive.ui.translations.potools import parse_po
  alert = EVENTS[log.OnroadEvent.EventName.porterButtonUnavailable][ET.PERMANENT]
  _, entries = parse_po(ROOT / 'openpilot/selfdrive/ui/translations' / f'app_{language}.po')
  translations = {entry.msgid: entry.msgstr for entry in entries}
  for text, size in ((alert.alert_text_1, 88), (alert.alert_text_2, 66)):
    assert translations[text]
    font_name = 'Inter-Bold.ttf' if language == 'en' else 'KaiGenGothicKR-Bold.ttf'
    font = ImageFont.truetype(str(ROOT / 'openpilot/selfdrive/assets/fonts' / font_name), size)
    left, _, right, _ = font.getbbox(translations[text])
    assert right - left <= 1860


def test_recovery_permission_uses_actual_fresh_vehicle_planner_and_radar_checks():
  source = ROOT / 'openpilot/selfdrive/controls/controlsd.py'
  tree = ast.parse(source.read_text())
  node = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == 'hudControl.porterRecoveryAllowed')
  for invalid in (None, 'carState', 'longitudinalPlan', 'radarState', 'other_car', 'direct_long'):
    CP, CS = cp(), state()
    if invalid == 'other_car':
      CP.carFingerprint = 'HYUNDAI_IONIQ_5'
    if invalid == 'direct_long':
      CP.openpilotLongitudinalControl = True
    obj = NS(CP=CP, sm=NS(all_checks=lambda services, invalid=invalid: invalid not in services))
    hud = car.CarControl.new_message().hudControl
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), {'self': obj, 'CS': CS, 'hudControl': hud})
    assert hud.porterRecoveryAllowed == (invalid is None)
