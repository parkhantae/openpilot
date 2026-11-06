import pytest

from openpilot.selfdrive.carrot import carrot_navi_control as control


class SubMaster:
  def __init__(self, message, timestamp=1):
    self.message = message
    self.logMonoTime = {'carrotNavi': timestamp}
    self.alive = {'carrotNavi': True}
    self.valid = {'carrotNavi': True}

  def __getitem__(self, service):
    assert service == 'carrotNavi'
    return self.message


def message(session='first', connected=True):
  return {'schemaVersion': 1, 'connected': connected, 'sessionId': session}


def test_repeated_consumers_parse_one_event_once(monkeypatch):
  original = control.parse_carrot_navi_control
  calls = []

  def parse(data):
    calls.append(data)
    return original(data)

  monkeypatch.setattr(control, 'parse_carrot_navi_control', parse)
  sm = SubMaster(message())
  cache = control.CarrotNaviControlCache()
  expected = original(sm.message)
  for _ in range(40):
    assert cache.read(sm) == expected
  assert len(calls) == 1
  # A new event must be parsed even if its item sequences are unchanged.
  sm.logMonoTime['carrotNavi'] = 2
  sm.message = message('second')
  assert cache.read(sm).session_id == 'second'
  assert len(calls) == 2


@pytest.mark.parametrize('flag', ['alive', 'valid'])
def test_inactive_service_clears_cache_and_reconnect_reparses(flag):
  sm = SubMaster(message())
  cache = control.CarrotNaviControlCache()
  first = cache.read(sm)
  getattr(sm, flag)['carrotNavi'] = False
  assert cache.read(sm) is None
  assert cache.control is None and cache.timestamp is None
  getattr(sm, flag)['carrotNavi'] = True
  sm.message = message('reconnected')
  assert cache.read(sm).session_id == 'reconnected'
  assert cache.control is not first


def test_disconnected_message_replaces_prior_control():
  cache = control.CarrotNaviControlCache()
  sm = SubMaster(message())
  assert cache.read(sm) is not None
  sm.logMonoTime['carrotNavi'] = 2
  sm.message = message(connected=False)
  assert cache.read(sm) is None
  assert cache.read(sm) is None


def test_missing_timestamp_does_not_reuse_old_control():
  cache = control.CarrotNaviControlCache()
  sm = SubMaster(message(), timestamp=0)
  assert cache.read(sm).session_id == 'first'
  sm.message = message('second')
  assert cache.read(sm).session_id == 'second'
  del sm.logMonoTime
  sm.message = message('third')
  assert cache.read(sm).session_id == 'third'


def test_control_route_never_iterates_past_limit():
  def points():
    for _ in range(control.MAX_ROUTE_POINTS):
      yield {'latitude': 37.0, 'longitude': 127.0}
    raise AssertionError('route reader materialized unused points')

  data = message()
  data['route'] = {'meta': {'present': True, 'sequence': 1}, 'polyline': points()}
  parsed = control.parse_carrot_navi_control(data)
  assert len(parsed.route.polyline) == control.MAX_ROUTE_POINTS
  assert all(point == (37.0, 127.0) for point in parsed.route.polyline)

