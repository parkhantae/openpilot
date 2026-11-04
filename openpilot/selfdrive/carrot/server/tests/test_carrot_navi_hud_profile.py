from openpilot.selfdrive.carrot.server.features.carrot_navi.bridge import CarrotNaviWebBridge


class FakeParams:
  def __init__(self, *, onroad_map: bool = False, cluster_hud: int = 0) -> None:
    self.writes: list[tuple[str, int]] = []
    self.onroad_map = onroad_map
    self.cluster_hud = cluster_hud

  def put_int_nonblocking(self, key: str, value: int) -> None:
    self.writes.append((key, value))

  def get_bool(self, key: str) -> bool:
    assert key == "CarrotNaviOnroad"
    return self.onroad_map

  def get_int(self, key: str) -> int:
    assert key == "ClusterHud"
    return self.cluster_hud


def test_hud_map_profile_is_reference_counted() -> None:
  bridge = CarrotNaviWebBridge(messaging_module=object())
  params = FakeParams()
  bridge._params = params

  bridge.set_hud_map_profile(True)
  bridge.set_hud_map_profile(True)
  bridge.set_hud_map_profile(False)
  bridge.set_hud_map_profile(False)

  assert params.writes == [
    ("CarrotNaviHudMapProfile", 1),
    ("CarrotNaviHudMapProfile", 1),
    ("CarrotNaviHudMapProfile", 1),
    ("CarrotNaviHudMapProfile", 0),
  ]


def test_status_counts_native_onroad_map_as_media_consumer() -> None:
  bridge = CarrotNaviWebBridge(messaging_module=object())
  bridge._params = FakeParams(onroad_map=True)

  status = bridge.status()

  assert status["directMapDemand"] is True
  assert status["mediaClients"] == 1
  assert status["connected"] is True
  assert status["hudMapProfile"] is False


def test_native_onroad_map_demand_respects_cluster_stream_gate() -> None:
  bridge = CarrotNaviWebBridge(messaging_module=object())
  bridge._params = FakeParams(onroad_map=True, cluster_hud=1)

  status = bridge.status()

  assert status["streamAllowed"] is False
  assert status["directMapDemand"] is False
  assert status["mediaClients"] == 0
  assert status["connected"] is False
