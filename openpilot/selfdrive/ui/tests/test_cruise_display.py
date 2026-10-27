from types import SimpleNamespace as NS

from openpilot.selfdrive.ui.cruise_display import displayed_cruise_speed_kph


def state(*, cluster=60, stock=50, enabled=True):
  return NS(vCruiseCluster=cluster, cruiseState=NS(speed=stock / 3.6, enabled=enabled))


def test_porter_displays_stock_cruise_setting_while_active():
  cp = NS(carFingerprint="HYUNDAI_PORTER_II_EV")
  controls = NS(deprecated=NS(vCruise=70))
  assert displayed_cruise_speed_kph(state(), controls, cp) == 50


def test_porter_uses_normal_target_when_stock_cruise_is_inactive():
  cp = NS(carFingerprint="HYUNDAI_PORTER_II_EV")
  controls = NS(deprecated=NS(vCruise=70))
  assert displayed_cruise_speed_kph(state(enabled=False), controls, cp) == 60


def test_other_cars_keep_cluster_and_controls_fallbacks():
  cp = NS(carFingerprint="OTHER")
  controls = NS(deprecated=NS(vCruise=70))
  assert displayed_cruise_speed_kph(state(), controls, cp) == 60
  assert displayed_cruise_speed_kph(state(cluster=0), controls, cp) == 70
