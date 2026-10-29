"""Opt-in Porter cancellation; the existing speed/button target is untouched."""
import math

from opendbc.car.hyundai.porter import PORTER_CRUISE_MAX_KPH, porter_lead_target_kph


def porter_cancel_target(planner, selected, navigation, ego, distance, relative, gap, *, lead_visible=False, gap_time_s=None):
  # Zero navigation/selected values mean unavailable; zero planner speed is a stop.
  candidates = [v for v in (selected, navigation) if v is not None and math.isfinite(v) and 0 < v <= 250]
  if planner is not None and math.isfinite(planner) and 0 <= planner <= 250:
    candidates.append(planner)
  if lead_visible and all(math.isfinite(v) for v in (ego, distance, relative)) and ego >= 0 and distance > 0:
    lead_speed = max(0., ego + relative) * 3.6
    # Reuse the existing selected-lead constraint without changing its 30 floor.
    cap = porter_lead_target_kph(PORTER_CRUISE_MAX_KPH, ego, distance, relative, gap, gap_time_s=gap_time_s)
    if cap <= 30 and lead_speed < 30:
      candidates.append(lead_speed)
  return min(candidates) if candidates else None


class PorterLowSpeedCancel:
  def __init__(self):
    self.since = None
    self.last_time = None
    self.active = False

  def update(self, now, target, *, eligible, cruise_enabled):
    clock_ok = math.isfinite(now) and (self.last_time is None or 0 <= now - self.last_time <= .1 + 1e-9)
    self.last_time = now if math.isfinite(now) else None
    if not eligible or not cruise_enabled:
      self.since, self.active = None, False
      return False
    if self.active:
      return True  # Finish cancellation until stock OFF; never engage/resume.
    if not clock_ok:
      self.since = None
      return False
    below = target is not None and math.isfinite(target) and 0 <= target < 30 - 1e-5
    if not below:
      self.since = None
      return False
    if self.since is None:
      self.since = now
    self.active = now - self.since >= .3 - 1e-9
    return self.active
