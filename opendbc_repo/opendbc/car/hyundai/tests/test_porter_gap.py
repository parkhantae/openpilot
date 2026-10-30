import unittest
from types import SimpleNamespace

from opendbc.car.hyundai.porter import (
  PORTER_GAP_TIME_S, PORTER_PLANNER_GAP_TIME_S, PorterLeadTracker, porter_base_gap_time_s, porter_conventional_cruise,
  porter_gap_time_s, porter_lead_reaction_s, porter_lead_target_kph,
)
from opendbc.car.hyundai.porter_cancel import porter_cancel_target


class TestPorterGap(unittest.TestCase):
  def test_applied_planner_time_overrides_legacy_and_base_settings(self):
    params = SimpleNamespace(get_int=lambda key: {'TFollowGap1': 45, 'PorterGap1': 200}[key])
    self.assertEqual(porter_gap_time_s(params, 1), .45)
    for applied in (.3, .579, 1.788, 3.5):
      self.assertEqual(porter_gap_time_s(params, 1, applied), applied)
    for invalid in (0, -.1, float('nan'), float('inf'), 31):
      self.assertEqual(porter_gap_time_s(params, 1, invalid), .45)
    self.assertEqual(porter_lead_target_kph(60, 10, 38, 0, 1, gap_time_s=3.5), 36)

  def test_actual_speed_path_uses_fresh_applied_tf_and_stale_base_fallback(self):
    import ast
    from pathlib import Path
    from opendbc.car.hyundai.porter import porter_navi_target_kph
    NS = SimpleNamespace
    tree = ast.parse((Path(__file__).resolve().parents[5] / 'openpilot/selfdrive/controls/controlsd.py').read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and
                'self.CP.carFingerprint == \'HYUNDAI_PORTER_II_EV\'' in ast.unparse(n.test) and
                'lead_target_kph =' in ast.unparse(n))
    code = compile(ast.Module(body=[node], type_ignores=[]), 'actual_porter_lead_gap', 'exec')
    for applied, fresh, reaction, expected in ((1., True, 8, 60), (2., True, 8, 30),
                                              (2., False, 8, 60), (2., True, 6, 60)):
      class SM(dict):
        frame = 0

        def all_checks(self, services, is_fresh=fresh):
          return is_fresh
      sm = SM(radarState=NS(leadOne=NS(status=True, dRel=48, vRel=-3)),
              selfdriveState=NS(personality=NS(raw=0)))
      obj = NS(CP=NS(carFingerprint='HYUNDAI_PORTER_II_EV'), sm=sm,
               params=NS(get_bool=lambda _:True,get_int=lambda key,r=reaction: int(r*10) if key=='PorterLeadReactionTime' else 100),
               porter_lead_tracker=PorterLeadTracker())
      hud = NS(setSpeed=60/3.6)
      env = dict(self=obj, CC=NS(enabled=True), CS=NS(cruiseState=NS(enabled=True, speed=60/3.6), vEgo=10),
                 speed_from_pcm=0, lp=NS(tFollow=applied), hudControl=hud, desired_kph=60, DT_CTRL=.01,
                 CV=NS(MS_TO_KPH=3.6, KPH_TO_MS=1/3.6), porter_navi_target_kph=porter_navi_target_kph,
                 porter_gap_time_s=porter_gap_time_s)
      env['porter_lead_reaction_s'] = porter_lead_reaction_s
      exec(code, env)
      self.assertAlmostEqual(hud.setSpeed*3.6, expected)

  def test_defaults_and_invalid_storage(self):
    for i, default in enumerate(PORTER_PLANNER_GAP_TIME_S, 1):
      for value in (0, 39, 301, 'bad'):
        def read(key, i=i, value=value):
          self.assertEqual(key, f'TFollowGap{i}')
          return int(value)
        self.assertEqual(porter_gap_time_s(SimpleNamespace(get_int=read), i), default)

  def test_live_selected_gap(self):
    values = dict(TFollowGap1=100, TFollowGap2=130, TFollowGap3=160, TFollowGap4=200)
    params = SimpleNamespace(get_int=lambda key: values[key])
    self.assertEqual(porter_gap_time_s(params, 2), 1.3)
    values['TFollowGap2'] = 250
    self.assertEqual(porter_gap_time_s(params, 2), 2.5)
    self.assertEqual(porter_gap_time_s(params, 1), 1.)

  def test_dedicated_mode_uses_saved_values_without_mutating_common_settings(self):
    values = dict(TFollowGap1=45,PorterGap1=40,PorterLeadReactionTime=60)
    enabled = [False]
    params = SimpleNamespace(get_int=lambda key: values[key],get_bool=lambda key: enabled[0])
    self.assertEqual(porter_base_gap_time_s(params,1),.45)
    self.assertEqual(porter_lead_reaction_s(params),8.)
    enabled[0] = True
    self.assertEqual(porter_base_gap_time_s(params,1),.4)
    self.assertEqual(porter_lead_reaction_s(params),6.)
    self.assertEqual(porter_gap_time_s(params,1,.58),.58)
    values['PorterGap1'] = 75
    self.assertEqual(porter_base_gap_time_s(params,1),.75)
    self.assertEqual(values['TFollowGap1'],45)

  def test_dedicated_invalid_values_use_conservative_defaults(self):
    for value in (0,39,301,'bad'):
      params = SimpleNamespace(get_bool=lambda _:True,get_int=lambda _,v=value:int(v))
      self.assertEqual([porter_base_gap_time_s(params,i) for i in range(1,5)],list(PORTER_GAP_TIME_S))
    for value in (0,39,81,'bad'):
      params = SimpleNamespace(get_bool=lambda _:True,get_int=lambda _,v=value:int(v))
      self.assertEqual(porter_lead_reaction_s(params),8.)

  def test_reaction_time_changes_button_cap_and_cancel_lead_constraint_together(self):
    # Recorded far/closing case: 79.1m at 35.1km/h, closing at8.62m/s.
    # 8s projects into the desired gap, 6s remains outside it.
    for reaction, expected in ((8.,30),(6.,50)):
      self.assertEqual(porter_lead_target_kph(50,35.1/3.6,79.1,-8.62,1,gap_time_s=.58,reaction_s=reaction),expected)
      self.assertEqual(PorterLeadTracker().update(0,50,50,35.1/3.6,79.1,-8.62,1,gap_time_s=.58,reaction_s=reaction),expected)
      target=porter_cancel_target(50,50,None,35.1/3.6,79.1,-8.62,1,lead_visible=True,gap_time_s=.58,reaction_s=reaction)
      self.assertAlmostEqual(target,(35.1/3.6-8.62)*3.6 if reaction==8 else 50)
      # Close slow/stopped leads still constrain even at the shortest setting.
      self.assertEqual(porter_lead_target_kph(50,10,20,-9,1,gap_time_s=.4,reaction_s=4),30)
      # An independent stop plan is never lifted by changing lead lookahead.
      self.assertEqual(porter_cancel_target(0,50,None,10,79,-8,1,lead_visible=True,gap_time_s=.4,reaction_s=reaction),0)

  def test_invalid_reaction_argument_preserves_eight_second_constraint(self):
    for reaction in (0,3.9,8.1,float('nan'),float('inf')):
      self.assertEqual(porter_lead_target_kph(50,10,50,-6,1,gap_time_s=1,reaction_s=reaction),30)

  def test_vehicle_selection_excludes_other_vehicles_and_direct_longitudinal(self):
    for name,pcm,longitudinal,expected in (('HYUNDAI_PORTER_II_EV',True,False,True),
                                           ('HYUNDAI_PORTER_II_EV',True,True,False),
                                           ('HYUNDAI_PORTER_II_EV',False,False,False),('OTHER',True,False,False)):
      self.assertEqual(porter_conventional_cruise(SimpleNamespace(carFingerprint=name,pcmCruise=pcm,
                                                               openpilotLongitudinalControl=longitudinal)),expected)
    self.assertFalse(porter_conventional_cruise(None))

  def test_threshold_changes_tracker_and_cancel_together(self):
    # At 36 km/h with a 30 m lead closing at 1 m/s, projected distance is 22 m.
    # 1s => 15 m threshold; 2s => 25 m threshold.
    for time_s, expected in ((1., 60), (2., 32.4)):
      self.assertAlmostEqual(porter_lead_target_kph(60, 10, 30, -1, 1, gap_time_s=time_s), expected)
      tracker = PorterLeadTracker()
      self.assertAlmostEqual(tracker.update(0, 60, 60, 10, 30, -1, 1, gap_time_s=time_s), expected)
    for time_s, expected in ((1., 60), (2., 25.2)):
      # Lead 25.2 km/h, projected 24m: only the longer configured gap constrains.
      target = porter_cancel_target(60, 60, None, 10, 48, -3, 1, lead_visible=True, gap_time_s=time_s)
      self.assertAlmostEqual(target, expected)

  def test_explicit_defaults_preserve_existing_targets(self):
    for level, time_s in enumerate(PORTER_GAP_TIME_S, 1):
      for distance in (5, 20, 40, 80):
        for relative in (-5, -1, 0, 1):
          args = (70, 15, distance, relative, level)
          self.assertEqual(porter_lead_target_kph(*args), porter_lead_target_kph(*args, gap_time_s=time_s))

  def test_sub_one_second_shared_setting_and_distance_floor(self):
    for value in (40, 50, 99, 100):
      params = SimpleNamespace(get_int=lambda key, v=value: v)
      self.assertEqual(porter_gap_time_s(params, 1), value / 100)
    # At 36 km/h projected range 12m: 0.5s keeps target; 1s constrains.
    self.assertEqual(porter_lead_target_kph(60, 10, 20, -1, 1, gap_time_s=.5), 60)
    self.assertAlmostEqual(porter_lead_target_kph(60, 10, 20, -1, 1, gap_time_s=1), 32.4)
    # Zero retains the existing 7m distance floor.
    self.assertAlmostEqual(porter_lead_target_kph(60, 10, 10, -1, 1, gap_time_s=0), 32.4)
