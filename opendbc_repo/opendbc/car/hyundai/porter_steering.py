"""Porter host-side yielding within the existing Hyundai safety limits."""

from opendbc.car import apply_driver_steer_torque_limits


# Classic Porter's native driver-torque check requires this retreat per sample
# while the previous command lies outside the driver's permitted torque range.
# This only reduces steering authority; it does not raise torque or weaken safety.
PORTER_DRIVER_RELEASE_STEP = 10
PORTER_NATIVE_STEER_MAX = 512


def apply_porter_steer_torque_limits(new_torque, last_torque, driver_torque, limits):
  torque = apply_driver_steer_torque_limits(new_torque, last_torque, driver_torque, limits)
  driver_scaled = driver_torque * limits.STEER_DRIVER_FACTOR
  # Use the native driver's envelope here, not the configurable host maximum.
  # The ordinary limiter above still enforces that host maximum. This avoids
  # overriding the configured release rate before native yielding is needed.
  lower = min(0, max(-PORTER_NATIVE_STEER_MAX,
                    -PORTER_NATIVE_STEER_MAX + (driver_scaled - limits.STEER_DRIVER_ALLOWANCE) * limits.STEER_DRIVER_MULTIPLIER))
  upper = max(0, min(PORTER_NATIVE_STEER_MAX,
                    PORTER_NATIVE_STEER_MAX + (driver_scaled + limits.STEER_DRIVER_ALLOWANCE) * limits.STEER_DRIVER_MULTIPLIER))

  # A slower configured DELTA_DOWN must not keep fighting the driver's input.
  # Stop at the driver's allowed range, and retain any faster existing retreat.
  if last_torque < lower:
    torque = max(torque, min(last_torque + PORTER_DRIVER_RELEASE_STEP, lower))
  elif last_torque > upper:
    torque = min(torque, max(last_torque - PORTER_DRIVER_RELEASE_STEP, upper))
  return int(round(torque))
