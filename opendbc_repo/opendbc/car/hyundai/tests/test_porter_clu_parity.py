import unittest
from types import SimpleNamespace as NS

from opendbc.can.packer import CANPacker
from opendbc.car.hyundai.hyundaican import create_clu11, create_clu11_button
from opendbc.car.hyundai.values import CAR


class TestPorterCluParity(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.packer = CANPacker('hyundai_kia_generic')

  def template(self, counter=9, parity=0):
    return dict(CF_Clu_CruiseSwState=0, CF_Clu_CruiseSwMain=0, CF_Clu_SldMainSW=0,
                CF_Clu_ParityBit1=parity, CF_Clu_VanzDecimal=.375, CF_Clu_Vanz=43.5,
                CF_Clu_SPEED_UNIT=0, CF_Clu_DetentOut=1, CF_Clu_RheostatLevel=7,
                CF_Clu_CluInfo=1, CF_Clu_AmpInfo=1, CF_Clu_AliveCnt1=counter)

  def test_real_packers_recompute_parity_for_switches_and_counter_without_mutation(self):
    cp = NS(carFingerprint=CAR.HYUNDAI_PORTER_II_EV, flags=0)
    writable = 7 | (1 << 5) | (15 << 28)
    for counter in range(16):
      for button in (0, 1, 2, 4):
        for main in (0, 1):
          for limiter in (0, 1):
            for parity in (0, 1):
              template = self.template(counter, parity)
              template.update(CF_Clu_CruiseSwMain=main, CF_Clu_SldMainSW=limiter)
              original = dict(template)
              source = int.from_bytes(self.packer.make_can_msg('CLU11', 0, template)[1], 'little')
              for factory in (create_clu11, create_clu11_button):
                address, payload, bus = factory(self.packer, (counter+1) % 16, template, button, cp)
                value = int.from_bytes(payload, 'little')
                self.assertEqual((address, bus), (0x4f1, 0))
                self.assertEqual(value & 7, button)
                self.assertEqual(value >> 28, (counter+1) % 16)
                # An independent parity check over the serialized wire fields.
                self.assertEqual(((value & 63).bit_count() + (value >> 28).bit_count()) % 2, 0)
                self.assertEqual(value & ~writable, source & ~writable)
                self.assertEqual(template, original)

  def test_counter_and_switch_change_regression_from_failed_set(self):
    cp = NS(carFingerprint=CAR.HYUNDAI_PORTER_II_EV, flags=0)
    template = self.template()
    template.update(CF_Clu_DetentOut=0, CF_Clu_RheostatLevel=0, CF_Clu_CluInfo=0, CF_Clu_AmpInfo=0)
    self.assertEqual(create_clu11_button(self.packer, 0, template, 2, cp)[1].hex(), 'e25700a0')
    # Previously copied parity produced c25700a0, which fails the wire check.
    invalid = int.from_bytes(bytes.fromhex('c25700a0'), 'little')
    self.assertEqual(((invalid & 63).bit_count() + (invalid >> 28).bit_count()) % 2, 1)

  def test_other_hyundai_models_keep_their_original_payload_policy(self):
    cp = NS(carFingerprint=CAR.HYUNDAI_SONATA, flags=0)
    for factory in (create_clu11, create_clu11_button):
      template = self.template()
      payload = factory(self.packer, 10, template, 2, cp)[1]
      self.assertEqual((payload[0] >> 5) & 1, template['CF_Clu_ParityBit1'])
