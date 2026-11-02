from analyze_buttons import ButtonFrame, analyze


def frame(t, button=0, counter=0, bus=0):
  return ButtonFrame(t, bus, bytes([button, 0, 0, (counter % 16) << 4]))


class TestButtonAnalysis:
  def test_physical_press_length_and_counter_wrap(self):
    frames = [frame(i * .02, 1, 12 + i) for i in range(8)] + [frame(.16, 0, 4)]
    result = analyze(frames, [], [], [])
    pulse = result['oem_presses'][0]
    assert pulse['press_frames'] == 8
    assert pulse['press_to_release_ms'] == 160
    assert pulse['counter_steps'] == [1] * 7

  def test_collision_can_exist_with_or_without_speed_response(self):
    oem = [frame(.02, 0, 1), frame(.04, 0, 2)]
    tx = [frame(.005, 1, 1), frame(.025, 1, 2), frame(.045, 0, 3)]
    for speed, expected in ((40, 'no_setting_change'), (41, 'directional_setting_change')):
      result = analyze(oem, tx, tx, [(0, 40), (.06, speed)])
      trial = result['injected_requests'][0]
      assert trial['same_counter_different_button_frames'] == 2
      assert trial['outcome'] == expected
      assert result['unmatched_intended_frames'] == 0

  def test_wrong_bus_is_not_a_counter_collision(self):
    tx = [frame(.005, 1, 1), frame(.025, 0, 2)]
    result = analyze([frame(.02, 0, 1, bus=2)], tx, [], [(0, 40), (.06, 40)])
    assert result['injected_requests'][0]['same_counter_different_button_frames'] == 0
    assert result['unmatched_intended_frames'] == 2

  def test_physical_input_prevents_attributing_feedback_to_injection(self):
    result = analyze([frame(.02, 2, 1)], [frame(.005, 1, 1)], [], [(0, 40), (.06, 39)])
    assert result['injected_requests'][0]['outcome'] == 'physical_button_overlap'

  def test_missing_feedback_and_release_are_not_success(self):
    result = analyze([], [frame(.005, 1, 1)], [], [])
    assert result['injected_requests'][0]['outcome'] == 'insufficient_speed_data'
    assert result['injected_requests'][0]['press_to_release_ms'] is None

  def test_opposite_change_and_cruise_off_are_distinct(self):
    tx = [frame(.005, 2, 1), frame(.025, 0, 2)]
    for speed, expected in ((42, 'opposite_setting_change'), (0, 'cruise_off')):
      result = analyze([], tx, tx, [(0, 40), (.06, speed)])
      assert result['injected_requests'][0]['outcome'] == expected

  def test_echo_payload_mismatch_is_detected(self):
    result = analyze([], [frame(0, 1, 1)], [frame(.01, 0, 1)], [])
    assert result['unmatched_intended_frames'] == 1
    assert result['unmatched_echo_frames'] == 1

  def test_unanswered_standby_set_is_not_a_cruise_off_edge(self):
    # Repeated zero set speeds in the uploaded standby failures never went ON.
    tx = [frame(.005, 2, 1), frame(.025, 0, 2)]
    result = analyze([], tx, tx, [(0, 0), (.02, 0), (.04, 0)])
    trial = result['injected_requests'][0]
    assert trial['outcome'] == 'no_engagement'
    assert trial['response_latency_ms'] is None
    assert trial['cruise_off_seconds'] is None
    assert not trial['cruise_off_after_response']

  def test_engagement_then_off_retains_the_observed_response(self):
    tx = [frame(10.005, 2, 1), frame(10.025, 0, 2)]
    trial = analyze([], tx, tx, [(10, 0), (10.05, 48), (10.2, 0)], origin=10)['injected_requests'][0]
    assert trial['outcome'] == 'setting_appeared'
    assert trial['response_latency_ms'] == 45
    assert trial['response_speed_kph'] == 48
    assert trial['cruise_off_seconds'] == .2
    assert trial['cruise_off_after_response']

  def test_speed_step_then_off_is_not_misreported_as_an_unanswered_step(self):
    for button, speed in ((1, 41), (2, 39)):
      tx = [frame(.005, button, 1), frame(.025, 0, 2)]
      trial = analyze([], tx, tx, [(0, 40), (.04, speed), (.1, 0)])['injected_requests'][0]
      assert trial['outcome'] == 'directional_setting_change'
      assert trial['response_latency_ms'] == 35
      assert trial['response_speed_kph'] == speed
      assert trial['cruise_off_after_response']

  def test_engagement_after_a_disengagement_does_not_acknowledge_old_step(self):
    tx = [frame(.005, 2, 1), frame(.025, 0, 2)]
    trial = analyze([], tx, tx, [(0, 40), (.02, 0), (.1, 35)])['injected_requests'][0]
    assert trial['outcome'] == 'cruise_off'
    assert trial['response_latency_ms'] is None
    assert trial['cruise_off_seconds'] == .02

  def test_next_request_bounds_feedback_attribution(self):
    tx = [frame(.005, 2, 1), frame(.025, 0, 2), frame(.1, 2, 3), frame(.12, 0, 4)]
    trials = analyze([], tx, tx, [(0, 0), (.04, 0), (.15, 48)])['injected_requests']
    assert [trial['outcome'] for trial in trials] == ['no_engagement', 'setting_appeared']
    assert [trial['response_latency_ms'] for trial in trials] == [None, 50]

  def test_physical_overlap_retains_causal_uncertainty_despite_response(self):
    tx = [frame(.005, 2, 1)]
    trial = analyze([frame(.02, 2, 2)], tx, tx, [(0, 0), (.05, 48)])['injected_requests'][0]
    assert trial['outcome'] == 'physical_button_overlap'
    assert trial['response_speed_kph'] == 48

  def test_missing_standby_feedback_is_not_classified_as_no_engagement(self):
    trial = analyze([], [frame(.005, 2, 1)], [], [(0, 0)])['injected_requests'][0]
    assert trial['outcome'] == 'insufficient_speed_data'
