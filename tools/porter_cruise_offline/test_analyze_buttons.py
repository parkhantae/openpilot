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
