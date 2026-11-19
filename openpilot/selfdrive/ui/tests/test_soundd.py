from openpilot.cereal import car
from openpilot.cereal import messaging
from openpilot.cereal.messaging import SubMaster, PubMaster
from openpilot.selfdrive.ui.soundd import (
  SELFDRIVE_STATE_TIMEOUT,
  Soundd,
  check_selfdrive_timeout_alert,
  resolve_sound_path,
  sound_list,
  dm_warning_volume,
)

import os
import time
import wave
import numpy as np
import pytest
from types import SimpleNamespace

from openpilot.common.basedir import BASEDIR

AudibleAlert = car.CarControl.HUDControl.AudibleAlert


class _SoundSubMaster:
  def __init__(self, countdown, *, selfdrive_updated=False, carrot_updated=True):
    self.updated = {"selfdriveState": selfdrive_updated, "carrotMan": carrot_updated}
    self.services = {
      "selfdriveState": SimpleNamespace(alertSound=SimpleNamespace(raw=AudibleAlert.none), alertType=""),
      "carrotMan": SimpleNamespace(leftSec=countdown),
    }

  def __getitem__(self, service):
    return self.services[service]


class TestSoundd:
  @pytest.mark.parametrize('name', ['driverDistracted', 'driverUnresponsive'])
  @pytest.mark.parametrize('volume', [0., 0.05, 0.69, 0.7, 0.85, 1., 1.5])
  @pytest.mark.parametrize('stage', [2, 3])
  def test_dm_warning_gain_reaches_pcm_even_with_user_mute(self, name, volume, stage):
    soundd = Soundd.__new__(Soundd)
    alert = AudibleAlert.promptDistracted if stage == 2 else AudibleAlert.warningImmediate
    soundd.current_alert = AudibleAlert.none
    soundd.current_alert_type = ''
    soundd.current_sound_frame = 0
    soundd.current_volume = volume
    samples = np.array([0.1, -0.3, 0.2, -0.4], dtype=np.float32)
    soundd.loaded_sounds = {alert: samples}
    sm = _SoundSubMaster(0, selfdrive_updated=True)
    sm['selfdriveState'].alertSound.raw = alert
    sm['selfdriveState'].alertType = f'{name}{stage}/permanent'
    soundd.get_audible_alert(sm)
    expected = max(0.7, volume) if stage == 2 else 1.
    np.testing.assert_allclose(soundd.get_sound_data(4), samples * expected)

  @pytest.mark.parametrize('volume', [0., 0.2, 0.9, 1.5])
  @pytest.mark.parametrize('alert', [AudibleAlert.promptDistracted, AudibleAlert.warningImmediate, AudibleAlert.prompt])
  def test_non_dm_sounds_keep_normal_volume(self, volume, alert):
    assert dm_warning_volume(alert, '', volume) == volume
    assert dm_warning_volume(alert, 'controlsMismatch/immediateDisable', volume) == volume
    assert dm_warning_volume(alert, 'driverDistracted1/permanent', volume) == volume

  def test_reused_wav_and_navigation_do_not_inherit_dm_gain(self):
    soundd = Soundd.__new__(Soundd)
    soundd.current_alert = AudibleAlert.none
    soundd.current_alert_type = ''
    soundd.current_sound_frame = 0
    soundd.loaded_sounds = {AudibleAlert.promptDistracted: np.ones(4, dtype=np.float32)}
    soundd.current_volume = 0.1
    soundd.carrot_count_down = 100
    soundd.update_alert(AudibleAlert.promptDistracted, 'driverDistracted2/permanent')
    soundd.update_alert(AudibleAlert.none)
    # Still finish the existing sound using its original DM floor.
    np.testing.assert_allclose(soundd.get_sound_data(4), .7)
    sm = _SoundSubMaster(11)
    sm['selfdriveState'].alertType = 'driverDistracted2/permanent'
    soundd.get_audible_alert(sm)
    assert soundd.current_alert_type == ''
    np.testing.assert_allclose(soundd.get_sound_data(4), .1)

  def test_countdown_reacts_to_carrot_man_update_without_selfdrive_update(self):
    soundd = Soundd.__new__(Soundd)
    soundd.carrot_count_down = 100
    soundd.current_alert = AudibleAlert.none
    soundd.current_sound_frame = 0
    soundd.loaded_sounds = {AudibleAlert.audio10: [0] * 10}

    soundd.get_audible_alert(_SoundSubMaster(10))

    assert soundd.carrot_count_down == 10
    assert soundd.current_alert == AudibleAlert.audio10

  def test_countdown_reset_allows_same_number_for_next_camera(self):
    soundd = Soundd.__new__(Soundd)
    soundd.carrot_count_down = 5
    soundd.current_alert = AudibleAlert.audio5
    soundd.current_sound_frame = 10
    soundd.loaded_sounds = {AudibleAlert.audio5: [0] * 10}

    soundd.get_audible_alert(_SoundSubMaster(100))
    assert soundd.carrot_count_down == 100
    assert soundd.current_alert == AudibleAlert.none

    soundd.get_audible_alert(_SoundSubMaster(5))
    assert soundd.carrot_count_down == 5
    assert soundd.current_alert == AudibleAlert.audio5

  def test_missing_sound_asset_falls_back_to_english_prompt(self, tmp_path):
    sound_dir = tmp_path / "sounds"
    fallback_dir = tmp_path / "sounds_eng"
    sound_dir.mkdir()
    fallback_dir.mkdir()
    prompt_path = fallback_dir / "prompt.wav"
    prompt_path.touch()

    assert resolve_sound_path(str(sound_dir), str(fallback_dir), "missing.wav") == str(prompt_path)

  def test_radar_alert_sound_assets(self):
    expected = {
      AudibleAlert.radarCutin: ("prompt.wav", 1.506),
      AudibleAlert.systemReady: ("prompt.wav", 1.506),
    }
    sound_dir = os.path.join(BASEDIR, "openpilot", "selfdrive", "assets", "sounds_eng")

    for alert, (filename, duration) in expected.items():
      assert sound_list[alert][:2] == (filename, 1)
      with wave.open(os.path.join(sound_dir, filename), "rb") as sound:
        assert sound.getnchannels() == 1
        assert sound.getsampwidth() == 2
        assert sound.getframerate() == 48000
        assert abs(sound.getnframes() / sound.getframerate() - duration) < 0.001

  def test_ready_chime_plays_once_and_warning_interrupts_it(self):
    soundd = Soundd.__new__(Soundd)
    soundd.current_alert = AudibleAlert.none
    soundd.current_alert_type = ''
    soundd.current_sound_frame = 0
    soundd.current_volume = 0.2
    soundd.loaded_sounds = {
      AudibleAlert.systemReady: np.ones(4, dtype=np.float32),
      AudibleAlert.warningImmediate: np.ones(4, dtype=np.float32),
    }
    soundd.update_alert(AudibleAlert.systemReady, 'systemReady/permanent')
    soundd.update_alert(AudibleAlert.none)
    np.testing.assert_allclose(soundd.get_sound_data(4), .2)
    np.testing.assert_allclose(soundd.get_sound_data(4), 0.)
    soundd.update_alert(AudibleAlert.none)
    soundd.update_alert(AudibleAlert.systemReady, 'systemReady/permanent')
    soundd.get_sound_data(1)
    soundd.update_alert(AudibleAlert.warningImmediate, 'driverDistracted3/permanent')
    np.testing.assert_allclose(soundd.get_sound_data(4), 1.)

  def test_completed_one_shot_alert_returns_to_none(self):
    soundd = Soundd.__new__(Soundd)
    soundd.current_alert = AudibleAlert.radarCutin
    soundd.current_sound_frame = 10
    soundd.loaded_sounds = {AudibleAlert.radarCutin: [0] * 10}

    soundd.update_alert(AudibleAlert.none)

    assert soundd.current_alert == AudibleAlert.none
    assert soundd.current_sound_frame == 0

  def test_unsupported_alert_is_ignored(self):
    soundd = Soundd.__new__(Soundd)
    soundd.current_alert = AudibleAlert.none
    soundd.current_sound_frame = 0
    soundd.loaded_sounds = {}

    soundd.update_alert(AudibleAlert.radarStationaryLead)

    assert soundd.current_alert == AudibleAlert.none

  def test_check_selfdrive_timeout_alert(self):
    sm = SubMaster(['selfdriveState'])
    pm = PubMaster(['selfdriveState'])

    for _ in range(100):
      cs = messaging.new_message('selfdriveState')
      cs.selfdriveState.enabled = True

      pm.send("selfdriveState", cs)

      time.sleep(0.01)

      sm.update(0)

      assert not check_selfdrive_timeout_alert(sm)

    for _ in range(SELFDRIVE_STATE_TIMEOUT * 110):
      sm.update(0)
      time.sleep(0.01)

    assert check_selfdrive_timeout_alert(sm)

  # TODO: add test with micd for checking that soundd actually outputs sounds



@pytest.fixture
def porter_sound():
  from openpilot.selfdrive.ui.soundd import make_porter_unavailable_sound
  soundd = Soundd.__new__(Soundd)
  soundd.current_alert = AudibleAlert.none
  soundd.current_alert_type = ''
  soundd.current_sound_frame = 0
  soundd.current_volume = 1.0
  soundd.carrot_count_down = 100
  soundd.porter_unavailable_sound = make_porter_unavailable_sound()
  soundd.loaded_sounds = {
    AudibleAlert.promptRepeat: np.full(50000, .25, dtype=np.float32),
    AudibleAlert.warningImmediate: np.full(50000, .5, dtype=np.float32),
  }
  return soundd


def test_porter_tone_repeats_two_beeps_once_per_second_across_callback_boundaries(porter_sound):
  from openpilot.selfdrive.ui.soundd import SAMPLE_RATE, PORTER_UNAVAILABLE_ALERT_TYPE
  porter_sound.update_alert(AudibleAlert.promptRepeat, PORTER_UNAVAILABLE_ALERT_TYPE)
  # Uneven chunks straddle both beep and one-second loop boundaries.
  chunks = []
  remaining = SAMPLE_RATE * 3
  while remaining:
    count = min(4096, remaining)
    chunks.append(porter_sound.get_sound_data(count))
    remaining -= count
    # A fresh selfdriveState every frame must not restart the one-second cycle.
    porter_sound.update_alert(AudibleAlert.promptRepeat, PORTER_UNAVAILABLE_ALERT_TYPE)
  output = np.concatenate(chunks).reshape(3, SAMPLE_RATE)
  np.testing.assert_array_equal(output[0], output[1])
  np.testing.assert_array_equal(output[0], output[2])
  for start, end in ((.01, .11), (.23, .33)):
    assert np.max(np.abs(output[0, int(start*SAMPLE_RATE):int(end*SAMPLE_RATE)])) > .6
  for start, end in ((.12, .22), (.34, 1.0)):
    assert not np.any(output[0, int(start*SAMPLE_RATE):int(end*SAMPLE_RATE)])


@pytest.mark.parametrize('elapsed', [1, 1000, 14000, 47000, 50001])
def test_porter_warning_stops_in_the_next_audio_buffer_when_display_clears(porter_sound, elapsed):
  from openpilot.cereal import log
  from openpilot.selfdrive.selfdrived.events import Events, ET
  from openpilot.selfdrive.selfdrived.alertmanager import AlertManager
  events = Events()
  events.add(log.OnroadEvent.EventName.porterButtonUnavailable)
  manager = AlertManager()
  manager.add_many(0, events.create_alerts([ET.PERMANENT]))
  manager.process_alerts(0, set())
  alert = manager.current_alert
  sm = _SoundSubMaster(100, selfdrive_updated=True)
  sm['selfdriveState'].alertSound.raw = alert.audible_alert
  sm['selfdriveState'].alertType = alert.alert_type
  porter_sound.get_audible_alert(sm)
  porter_sound.get_sound_data(elapsed)
  # The same alert manager that selects the screen also selects the sound.
  manager.process_alerts(alert.duration + 1, set())
  assert manager.current_alert.alert_text_1 == ''
  sm['selfdriveState'].alertSound.raw = manager.current_alert.audible_alert
  sm['selfdriveState'].alertType = manager.current_alert.alert_type
  porter_sound.get_audible_alert(sm)
  assert porter_sound.current_alert == AudibleAlert.none
  assert not np.any(porter_sound.get_sound_data(4096))


def test_porter_warning_yields_to_critical_alert_and_restarts_after_it(porter_sound):
  from openpilot.selfdrive.ui.soundd import PORTER_UNAVAILABLE_ALERT_TYPE
  porter_sound.update_alert(AudibleAlert.promptRepeat, PORTER_UNAVAILABLE_ALERT_TYPE)
  porter_sound.get_sound_data(100)
  porter_sound.update_alert(AudibleAlert.warningImmediate, 'driverDistracted3/permanent')
  np.testing.assert_allclose(porter_sound.get_sound_data(100), .5)
  porter_sound.update_alert(AudibleAlert.promptRepeat, PORTER_UNAVAILABLE_ALERT_TYPE)
  assert porter_sound.current_sound_frame == 0
  np.testing.assert_array_equal(porter_sound.get_sound_data(100), porter_sound.porter_unavailable_sound[:100])


def test_porter_tone_does_not_replace_other_events_using_prompt_repeat(porter_sound):
  from openpilot.selfdrive.ui.soundd import PORTER_UNAVAILABLE_ALERT_TYPE
  porter_sound.update_alert(AudibleAlert.promptRepeat, 'otherWarning/warning')
  np.testing.assert_allclose(porter_sound.get_sound_data(100), .25)
  porter_sound.update_alert(AudibleAlert.promptRepeat, PORTER_UNAVAILABLE_ALERT_TYPE)
  assert porter_sound.current_sound_frame == 0
  porter_sound.get_sound_data(100)
  porter_sound.update_alert(AudibleAlert.promptRepeat, 'otherWarning/warning')
  assert porter_sound.current_sound_frame == 0
  np.testing.assert_allclose(porter_sound.get_sound_data(100), .25)


def test_alert_manager_selects_critical_warning_before_porter_tone(porter_sound):
  from openpilot.cereal import log
  from openpilot.selfdrive.selfdrived.events import Events, ET
  from openpilot.selfdrive.selfdrived.alertmanager import AlertManager
  events = Events()
  events.add(log.OnroadEvent.EventName.porterButtonUnavailable)
  events.add(log.OnroadEvent.EventName.controlsMismatch)
  manager = AlertManager()
  alerts = events.create_alerts([ET.PERMANENT, ET.IMMEDIATE_DISABLE])
  manager.add_many(0, alerts)
  manager.process_alerts(0, set())
  assert manager.current_alert.alert_type == 'controlsMismatch/immediateDisable'
  sm = _SoundSubMaster(100, selfdrive_updated=True)
  sm['selfdriveState'].alertType = manager.current_alert.alert_type
  sm['selfdriveState'].alertSound.raw = manager.current_alert.audible_alert
  porter_sound.get_audible_alert(sm)
  np.testing.assert_allclose(porter_sound.get_sound_data(100), .5)


@pytest.mark.parametrize('volume', [0., .2, 1.])
def test_porter_tone_obeys_existing_volume(porter_sound, volume):
  from openpilot.selfdrive.ui.soundd import PORTER_UNAVAILABLE_ALERT_TYPE
  porter_sound.current_volume = volume
  porter_sound.update_alert(AudibleAlert.promptRepeat, PORTER_UNAVAILABLE_ALERT_TYPE)
  np.testing.assert_allclose(porter_sound.get_sound_data(1000), porter_sound.porter_unavailable_sound[:1000] * volume)


def test_production_sound_loader_prepares_the_porter_tone(monkeypatch):
  from openpilot.selfdrive.ui import soundd as module
  soundd = Soundd.__new__(Soundd)
  soundd.lang = 'en'
  monkeypatch.setattr(module, 'sound_list', {AudibleAlert.promptRepeat: sound_list[AudibleAlert.promptRepeat]})
  soundd.load_sounds()
  assert AudibleAlert.promptRepeat in soundd.loaded_sounds
  assert len(soundd.porter_unavailable_sound) == module.SAMPLE_RATE
  assert soundd.porter_unavailable_sound.dtype == np.float32
