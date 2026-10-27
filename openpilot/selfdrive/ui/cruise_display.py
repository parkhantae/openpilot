from openpilot.common.constants import CV


PORTER_EV_FINGERPRINT = "HYUNDAI_PORTER_II_EV"


def displayed_cruise_speed_kph(car_state, controls_state, car_params):
  """Return the set speed represented by the vehicle's active cruise display."""
  if (car_params is not None and car_params.carFingerprint == PORTER_EV_FINGERPRINT and
      car_state.cruiseState.enabled and car_state.cruiseState.speed > 0):
    return float(car_state.cruiseState.speed * CV.MS_TO_KPH)

  v_cruise_cluster = car_state.vCruiseCluster
  return float(controls_state.deprecated.vCruise if v_cruise_cluster == 0.0 else v_cruise_cluster)
