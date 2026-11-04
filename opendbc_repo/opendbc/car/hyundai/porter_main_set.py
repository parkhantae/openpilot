"""Driver-authorized bounded SET pulses; no remembered-speed RES requests."""
import math


class PorterMainSet:
  def __init__(self, initial_main=False, allow_startup_gas=False, two_press=False):
    self.main = bool(initial_main)
    self.main_known = False
    self.previous_main = False
    self.previous_stock = False
    self.armed = False
    self.last_time = None
    self.last_key = None
    self.sample_key = None
    self.sample_seen = 0.
    self.retry_sample_delay = 0.
    self.preferred_sample_delay = 0.
    self.request_sample_delay = 0.
    self.slot_wait_since = None
    self.since = None
    self.pressing = False
    self.pedal_started = False
    self.started = 0.
    self.frames = 0
    self.next_request = 0.
    self.unknown_retry_at = 0.
    self.attempts = 0
    self.retry_wait = 1.
    self.pending_release = False
    self.previous_gas = False
    self.gas_release_since = None
    self.main_since = None
    self.raw_previous_gas = False
    self.rearm_gas_since = None
    self.rearm_release_since = None
    self.sent_key = None
    self.awaiting_stock = False
    self.requests = 0
    self.acks = 0
    self.timeouts = 0
    self.response = "idle"
    self.allow_startup_gas = allow_startup_gas
    self.startup_released = False
    self.startup_gas_since = None
    self.startup_valid_since = None
    self.startup_grant = False
    self.startup_grant_since = None
    self.two_press = two_press
    self.pair_remaining = 0
    self.pair_deadline = None
    self.pair_index = 0
    self.pair_gas_since = None
    self.response_started = 0.

  def update(self, now, key, *, main_pressed, manual_button, blocked, request, stock_enabled, configured,
             gas_pressed=False, pedal_only=False, release_eligible=True):
    # The production two-press policy always needs a fresh pedal cue, including
    # while lateral control is active. Legacy profiles/tests retain their path.
    pedal_only = pedal_only or self.two_press
    if key is not None and key != self.sample_key:
      self.sample_key = key
      self.sample_seen = now
    fresh = key is not None and key != self.last_key
    # The stock ECU did not acknowledge the immediate RX-relative slot in a
    # vehicle log. Try the other 10 ms control slot after an unanswered pair,
    # while retaining one transmission at most for each received CLU11 sample.
    # Driver input, invalid state and release frames always bypass this trial.
    pair_continuing = self.pressing or self.pair_remaining > 0
    bypass_delay = (not self.two_press or main_pressed or manual_button or blocked or not configured or
                    not request or (stock_enabled and not pair_continuing) or gas_pressed or self.pending_release or
                    key is None or not math.isfinite(now))
    if self.retry_sample_delay and not bypass_delay:
      if fresh and now - self.sample_seen < self.retry_sample_delay - 1e-9:
        self.slot_wait_since = now if self.slot_wait_since is None else self.slot_wait_since
        if now - self.slot_wait_since >= .1 - 1e-9:
          # Scheduling must not starve automatic SET when the delayed slot is
          # unavailable. Fall back to the original immediate slot.
          self.retry_sample_delay = 0.
          self.slot_wait_since = None
        else:
          fresh = False
      elif fresh:
        self.slot_wait_since = None
    else:
      self.slot_wait_since = None
    if fresh:
      self.last_key = key
    clock_ok = math.isfinite(now) and (self.last_time is None or 0 <= now - self.last_time <= .1 + 1e-9)
    self.last_time = now
    if not clock_ok:
      self.armed = False
    if not configured:
      # Disabling automatic SET revokes permission, not the vehicle's MAIN
      # state. Erasing MAIN here also inverts subsequent physical MAIN edges
      # and leaves a known-OFF latch after the option is enabled again.
      self.armed = False
    tx_fresh = key is not None and key != self.sent_key

    def send(button):
      self.sent_key = key
      # A missing response does not reveal whether Panda accepted the pulse.
      # Cover its maximum three-second wait from the last possible SET/release,
      # rather than guessing native attempt phase from intended requests.
      self.unknown_retry_at = now + 3.
      if self.response in ("no_response", "interrupted"):
        self.next_request = max(self.next_request, self.unknown_retry_at)
      if self.two_press and button == 0:
        self.next_request = max(self.next_request, now + .08 if self.pair_remaining else self.unknown_retry_at)
      return button

    stock_rising = stock_enabled and not self.previous_stock
    self.previous_stock = stock_enabled
    observation_started = self.response_started if self.two_press else self.started
    if self.awaiting_stock and clock_ok and now - observation_started > .5 + 1e-9:
      self.awaiting_stock = False
      self.timeouts += 1
      self.response = "no_response"
      self.next_request = max(self.next_request, self.unknown_retry_at)
      if self.two_press:
        # Change only the next qualified pedal cycle's RX-relative phase. The
        # pair bounds, native quiet period and fresh-pedal requirement remain.
        self.retry_sample_delay = .01 - self.request_sample_delay
    if stock_rising:
      if (self.awaiting_stock and clock_ok and configured and now - observation_started <= .5 + 1e-9 and
          not manual_button and not main_pressed and not blocked and not gas_pressed):
        self.acks += 1
        self.response = "engaged"
        if self.two_press:
          self.preferred_sample_delay = self.request_sample_delay
          self.retry_sample_delay = self.preferred_sample_delay
      elif self.awaiting_stock:
        self.response = "interrupted"
        self.next_request = max(self.next_request, self.unknown_retry_at)
      self.awaiting_stock = False
    # A new accelerator press interrupts the pending SET observation too.
    # The pulse stops below, but retaining awaiting_stock would count the
    # driver's interruption as an ECU timeout or attribute a later ON to it.
    if manual_button or main_pressed or blocked or gas_pressed or not configured or not clock_ok:
      if manual_button or main_pressed or not configured:
        self.retry_sample_delay = self.preferred_sample_delay
      if self.awaiting_stock:
        self.response = "interrupted"
        self.next_request = max(self.next_request, self.unknown_retry_at)
      self.awaiting_stock = False
    if configured and stock_rising and not main_pressed:
      # Stock engagement proves MAIN is on, but never restores revoked permission.
      self.main = True
      self.main_known = True
      if self.main_since is None:
        self.main_since = now
    if fresh:
      if main_pressed and not self.previous_main:
        self.main_known = True
        self.main = not self.main
        self.armed = self.main and configured
        self.main_since = now if self.main else None
      self.previous_main = main_pressed
      if manual_button == 4:
        self.armed = False
    if blocked:
      self.armed = False
    startup_ready = (self.allow_startup_gas and configured and self.main and not self.main_known and clock_ok and
                     not blocked and not main_pressed and not manual_button and not stock_enabled)
    if not startup_ready:
      self.startup_released = self.startup_grant = False
      self.startup_gas_since = self.startup_valid_since = None
    else:
      if self.startup_valid_since is None:
        self.startup_valid_since = now
      if not gas_pressed:
        self.startup_released = True
      if gas_pressed and not self.raw_previous_gas and self.startup_released:
        self.startup_gas_since = now
      elif not gas_pressed and self.raw_previous_gas:
        if (self.startup_gas_since is not None and now - self.startup_gas_since >= .1 - 1e-9 and
            now - self.startup_valid_since >= .5 - 1e-9 and request):
          # A fresh driver pedal cycle grants one bounded trial, NOT knowledge
          # of OEM MAIN state. Only actual stock ON may synchronize that state.
          self.startup_grant = True
          self.startup_grant_since = now
          self.previous_gas = True
          self.main_since = self.startup_valid_since
        self.startup_gas_since = None
      if gas_pressed or not request:
        self.startup_grant = False
      if (self.startup_grant and not self.pressing and self.startup_grant_since is not None and
          now - self.startup_grant_since > .1 + 1e-9):
        self.startup_grant = False
    rearm_ready = (configured and self.main and self.main_known and clock_ok and not blocked and not main_pressed and
                   not manual_button and not stock_enabled)
    if not rearm_ready or self.armed:
      self.rearm_gas_since = None
      self.rearm_release_since = None
    else:
      if gas_pressed:
        self.rearm_release_since = None
        if not self.raw_previous_gas:
          self.rearm_gas_since = now
      elif not gas_pressed and self.raw_previous_gas:
        if self.rearm_gas_since is not None and now - self.rearm_gas_since >= .1 - 1e-9 and release_eligible:
          self.rearm_release_since = now
        self.rearm_gas_since = None
      if self.rearm_release_since is not None:
        if not release_eligible or now - self.rearm_release_since > .1 + 1e-9:
          self.rearm_release_since = None
        elif request:
          # A brief lead/plan block at release must not erase a fresh driver
          # cycle after brake/CANCEL. Rearm only with a currently valid request,
          # and keep the original release time so recovery cannot renew the cue.
          self.armed = True
          self.gas_release_since = self.rearm_release_since
          self.rearm_release_since = None
    self.raw_previous_gas = gas_pressed
    eligible = (self.armed or self.startup_grant) and configured and clock_ok and not blocked and not main_pressed and not manual_button
    pair_continuing = self.two_press and (self.pressing or self.pair_remaining > 0)
    qualified_pair_release = False
    if self.two_press:
      if not eligible or stock_enabled:
        self.pair_gas_since = None
      elif gas_pressed:
        if not self.previous_gas:
          self.pair_gas_since = now
      elif self.previous_gas:
        qualified_pair_release = self.pair_gas_since is not None and now - self.pair_gas_since >= .1 - 1e-9
        self.pair_gas_since = None
    if self.two_press and (not eligible or gas_pressed or not request or
                           not release_eligible or key is None or
                           (self.pair_deadline is not None and now > self.pair_deadline + 1e-9)):
      # A second press is a bounded continuation of this release, never a cue
      # retained through a new pedal, driver override, target loss or RX gap.
      if self.pair_remaining or self.pressing:
        self.next_request = max(self.next_request, self.unknown_retry_at)
      self.pair_remaining = 0
      self.pair_deadline = None
    if eligible and not stock_enabled and self.previous_gas and not gas_pressed:
      self.gas_release_since = now if not self.two_press or qualified_pair_release else None
    self.previous_gas = gas_pressed if eligible and not stock_enabled else False
    if not eligible or stock_enabled or gas_pressed:
      self.gas_release_since = None
    elif not request and self.gas_release_since is not None and now - self.gas_release_since > .1 + 1e-9:
      # A brief lead/plan transition may straddle pedal release. Keep only a
      # 100ms observation window; never turn it into a delayed engagement queue.
      self.gas_release_since = None
    if (pedal_only and self.gas_release_since is not None and
        now - self.gas_release_since > .1 + 1e-9):
      # Inactive controls must not queue a later engagement behind retry limits.
      self.gas_release_since = None
    if (not eligible or (stock_enabled and not pair_continuing) or not request or gas_pressed or
        (pedal_only and self.pressing and not self.pedal_started)):
      self.since = None
      if self.pressing:
        self.pending_release = True
        self.startup_grant = False
      self.pressing = False
      if stock_enabled:
        self.attempts = 0
      if tx_fresh and self.pending_release and not main_pressed and not manual_button:
        self.pending_release = False
        return send(0)
      return None
    if self.pending_release:
      if tx_fresh:
        self.pending_release = False
        return send(0)
      return None
    if self.pressing:
      if now - self.started >= (.06 if self.two_press else .12) - 1e-9 or self.frames >= (3 if self.two_press else 6):
        self.pressing = False
        self.startup_grant = False
        self.pending_release = True
        self.next_request = now + (.08 if self.two_press and self.pair_remaining else self.retry_wait)
        if tx_fresh:
          self.pending_release = False
          return send(0)
      elif fresh and tx_fresh:
        # The alternate timing trial may consume one still-current sample on
        # the following 10 ms control tick. sent_key still prevents a second
        # transmission from that sample, and Panda checks the latest counter.
        self.frames += 1
        return send(2)
      return None
    if pedal_only:
      self.since = None
    elif self.since is None:
      self.since = now
    # Gas release is the driver's immediate SET cue. Do not add a 100ms
    # confirmation dwell once all request/override guards are already valid.
    # Native MAIN settling, retry quiet periods and fresh-sample timing remain.
    release_ready = (self.gas_release_since is not None and self.main_since is not None and
                     now - self.main_since >= .5 - 1e-9)
    pair_ready = (self.two_press and self.main_known and self.pair_remaining > 0 and
                  self.pair_deadline is not None and now <= self.pair_deadline - .06 + 1e-9)
    start_ready = release_ready or pair_ready or (not pedal_only and now - self.since >= .5 - 1e-9)
    if now + (1e-9 if self.two_press else 0.) >= self.next_request and start_ready:
      # A pedal release or retry deadline between RX updates must wait for
      # the next sample, rather than sending its predecessor late. Normal
      # engaged speed matching keeps its independent timing policy.
      if not fresh or not tx_fresh:
        return None
      second_press = pair_ready and not release_ready
      self.pedal_started = release_ready or second_press
      if not second_press:
        self.response_started = now
        self.request_sample_delay = self.retry_sample_delay
      if self.two_press:
        self.pair_index = 2 if second_press else 1
        self.pair_remaining = int(not second_press and self.main_known)
        # New versioned Panda profile: two <=60ms/3-frame presses separated by
        # an explicit release and 80ms gap, at most six SET frames in 240ms.
        self.pair_deadline = now + .24 if self.pair_remaining else None
      self.awaiting_stock = not stock_enabled
      self.requests += 1
      self.response = "engaged" if stock_enabled else "pending"
      self.gas_release_since = None
      self.pressing = True
      self.started = now
      self.frames = 1
      self.attempts += 1
      self.retry_wait = 3. if self.attempts >= 3 else 1.
      if self.attempts >= 3:
        self.attempts = 0
      # Reserve the retry quiet period at the first SET, including attempts
      # interrupted by a new pedal/target change before normal pulse completion.
      self.next_request = now + self.retry_wait
      return send(2)
    return None
