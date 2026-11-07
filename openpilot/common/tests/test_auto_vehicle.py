import copy

import pytest

from openpilot.common import auto_vehicle as av
from openpilot.common.params import Params


@pytest.fixture
def params(tmp_path):
  p = Params(str(tmp_path / 'params'))
  for key in av.IONIQ_SETTINGS:
    p.put(key, p.get_default_value(key))
  p.put('CarName', av.PORTER)
  p.put('CarSelected3', av.CAR_LABELS[av.PORTER])
  p.put_bool('PorterAutoSetMain', True)
  p.put_bool('PorterAutoCancelBelow30', True)
  p.put_bool('PorterGapUse', True)
  return p


def snapshot(params):
  return {(k.decode() if isinstance(k, bytes) else k): params.get(k) for k in params.all_keys()}


def test_only_requested_seven_settings_change_and_porter_returns_exactly(params):
  params.put('CalibrationParams', b'untouched camera calibration')
  params.put('LiveTorqueParameters', b'untouched learned torque')
  params.put_int('PorterGap1', 45)
  params.put_int('TFollowGap1', 65)
  params.put_int('AlwaysLateral', 1)
  before = snapshot(params)
  av.apply_vehicle_settings(params, av.IONIQ5, av.prepare_settings(params))
  after = snapshot(params)
  changed = {k for k in before if before[k] != after[k]}
  assert changed <= set(av.IONIQ_SETTINGS) | {'AutoVehiclePorterBase', 'CarName', 'CarSelected3'}
  assert {k: params.get(k) for k in av.IONIQ_SETTINGS} == av.IONIQ_SETTINGS
  av.apply_vehicle_settings(params, av.PORTER, av.prepare_settings(params))
  restored = snapshot(params)
  assert {k: restored[k] for k in before if k != 'AutoVehiclePorterBase'} == {
    k: v for k, v in before.items() if k != 'AutoVehiclePorterBase'
  }


def test_ioniq_values_never_overwrite_porter_baseline(params):
  base = {k: params.get(k) for k in av.IONIQ_SETTINGS}
  for _ in range(3):
    av.apply_vehicle_settings(params, av.IONIQ5, av.prepare_settings(params))
    assert params.get('AutoVehiclePorterBase')['porter'] == base
  av.apply_vehicle_settings(params, av.PORTER, av.prepare_settings(params))
  assert {k: params.get(k) for k in av.IONIQ_SETTINGS} == base
  params.put_int('CustomSR', 155)
  av.apply_vehicle_settings(params, av.IONIQ5, av.prepare_settings(params))
  av.apply_vehicle_settings(params, av.PORTER, av.prepare_settings(params))
  assert params.get_int('CustomSR') == 155


def test_missing_porter_baseline_cannot_assume_current_ioniq_values(params):
  params.put('CarName', av.IONIQ5)
  params.put('CarSelected3', av.CAR_LABELS[av.IONIQ5])
  before = snapshot(params)
  with pytest.raises(ValueError, match='Save the Porter baseline'):
    av.apply_vehicle_settings(params, av.IONIQ5, av.prepare_settings(params))
  assert snapshot(params) == before


@pytest.mark.parametrize('failure_key', list(av.IONIQ_SETTINGS) + ['CarSelected3', 'CarName'])
def test_failed_write_rolls_back_all_seven_and_vehicle_identity(params, failure_key):
  data = av.prepare_settings(params)
  before = snapshot(params)

  class FailOnce:
    failed = False

    def __getattr__(self, name):
      return getattr(params, name)

    def put(self, key, value):
      if key == failure_key and not self.failed:
        self.failed = True
        raise OSError('simulated disk failure')
      params.put(key, value)

  with pytest.raises(OSError):
    av.apply_vehicle_settings(FailOnce(), av.IONIQ5, data)
  assert snapshot(params) == before


def test_power_loss_recovers_before_next_snapshot(params):
  data = av.prepare_settings(params)
  before = snapshot(params)

  class PowerLoss:
    def __getattr__(self, name):
      return getattr(params, name)

    def put(self, key, value):
      if key == 'CustomSR':
        raise SystemExit('simulated power loss')
      params.put(key, value)

  with pytest.raises(SystemExit):
    av.apply_vehicle_settings(PowerLoss(), av.IONIQ5, data)
  assert params.get_int('HyundaiCameraSCC') == 2
  assert 'pending' in params.get('AutoVehiclePorterBase')
  av.prepare_settings(params)
  assert snapshot(params) == before


@pytest.mark.parametrize('bad', [[], {'version': 2}, {'version': 1, 'porter': {'CustomSR': 140}, 'active': av.PORTER}])
def test_corrupt_baseline_never_applies_partial_defaults(params, bad):
  params.put('AutoVehiclePorterBase', bad)
  before = snapshot(params)
  with pytest.raises(ValueError):
    av.prepare_settings(params)
  assert snapshot(params) == before


def test_unknown_vehicle_does_not_write_settings(params):
  data = av.prepare_settings(params)
  before = snapshot(params)
  with pytest.raises(ValueError):
    av.apply_vehicle_settings(params, 'HYUNDAI_IONIQ_5_PE', copy.deepcopy(data))
  assert snapshot(params) == before


def test_live_ready_session_cannot_apply_another_vehicle(params):
  data = av.prepare_settings(params)
  params.put_bool('AutoVehicleReady', True)
  before = snapshot(params)
  with pytest.raises(RuntimeError):
    av.apply_vehicle_settings(params, av.IONIQ5, data)
  assert snapshot(params) == before
