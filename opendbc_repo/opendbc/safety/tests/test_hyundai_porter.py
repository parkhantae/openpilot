import unittest
from hyundai_porter_testlib import lib, packet, data, rx, seed, init, engage


class TestNativePorter(unittest.TestCase):
    def test_fresh_stock_cruise_allows_speed_buttons(self):
        engage()
        for button in (1, 2):
            self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button))))

    def test_low_speed_stock_cruise_allows_speed_buttons(self):
        init()
        seed(button=2, target=5)
        self.assertTrue(lib.get_controls_allowed())
        for button in (1, 2):
            self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button))))

    def test_no_engagement_or_resume_from_transmit(self):
        init()
        for button in (1, 2):
            self.assertFalse(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button))))
        self.assertFalse(lib.get_controls_allowed())

    def test_explicit_release_does_not_require_engagement(self):
        init()
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=0))))
        main = bytearray(data(0x4f1, button=0));main[0] |= 8
        self.assertFalse(lib.safety_tx_hook(packet(0x4f1, main)))

    def test_positive_target_without_recent_button_cannot_enable(self):
        init()
        for i in range(12):
            seed(counter=i+1)
        seed(counter=13, target=50)
        self.assertFalse(lib.get_controls_allowed())

    def test_delayed_target_within_one_second_of_physical_set_enables(self):
        init()
        lib.set_timer(2000)
        seed(counter=1, button=2)
        for i in range(20):
            lib.set_timer(22000 + i * 20000)
            seed(counter=i + 2)
        self.assertFalse(lib.get_controls_allowed())
        lib.set_timer(500000)
        seed(counter=6, target=31)
        self.assertTrue(lib.get_controls_allowed())

    def test_physical_set_rearms_buttons_when_cruise_is_already_active(self):
        init()
        lib.set_timer(2000)
        seed(counter=1, target=50)
        self.assertFalse(lib.get_controls_allowed())
        lib.set_timer(3000)
        seed(counter=2, target=50, button=2)
        self.assertTrue(lib.get_controls_allowed())
        self.assertTrue(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=1))))

    def test_brake_parking_hold_and_gear_block(self):
        for address, changes in ((0x394, {'brake':True}), (0x394, {'park':True}),
                                 (0x507, {'hold':True}), (0x372, {'drive':False})):
            engage()
            self.assertTrue(rx(address, counter=3, **changes))
            for button in (1, 2):
                self.assertFalse(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=button))))

    def test_gas_blocks_buttons_even_if_steering_allowed(self):
        engage()
        lib.set_alternative_experience(1)
        rx(0x371, target=31, gas=True)
        self.assertFalse(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=1))))

    def test_age_limit_blocks_buttons_before_one_second_tick(self):
        engage()
        lib.set_timer(104001)
        self.assertFalse(lib.safety_tx_hook(packet(0x4f1, data(0x4f1, button=1))))

    def test_crc_corruption_blocks(self):
        for addr in (0x394, 0x386):
            engage()
            payload=bytearray(data(addr, counter=3));payload[0]^=1
            self.assertFalse(lib.safety_rx_hook(packet(addr,payload)))
            self.assertFalse(lib.safety_tx_hook(packet(0x4f1,data(0x4f1,button=2))))

    def test_zero_invalid_target_and_manual_cancel(self):
        for value in (0, 1, 4, 161, 255):
            engage();rx(0x371,target=value)
            self.assertFalse(lib.get_controls_allowed())
        engage();rx(0x4f1,button=4,counter=3)
        self.assertFalse(lib.get_controls_allowed())

    def test_no_acceleration_diagnostic_wrong_bus_or_main(self):
        engage()
        for addr in (0x420,0x421,0x50a,0x389,0x38d,0x7d0):
            self.assertFalse(lib.safety_tx_hook(packet(addr,bytes(8))))
        self.assertFalse(lib.safety_tx_hook(packet(0x4f1,data(0x4f1,button=1),bus=2)))
        main=bytearray(data(0x4f1,button=1));main[0]|=8
        self.assertFalse(lib.safety_tx_hook(packet(0x4f1,main)))

    def test_missing_packet_never_allows(self):
        for missing in (0x371,0x394,0x386,0x4f1,0x372,0x507):
            lib.set_safety_hooks(8,1025);lib.init_tests();lib.set_timer(1000)
            for addr in (0x386,0x394,0x4f1,0x372,0x507,0x371):
                if addr!=missing:rx(addr,button=2,target=31)
            self.assertFalse(lib.safety_config_valid())
            self.assertFalse(lib.safety_tx_hook(packet(0x4f1,data(0x4f1,button=1))))

    def test_conflicting_modes_fail_closed(self):
        for param in (1024,1025|2,1025|4,1025|8,1025|2048):
            lib.set_safety_hooks(8,param);lib.init_tests()
            self.assertFalse(lib.safety_tx_hook(packet(0x4f1,data(0x4f1,button=1))))

    def test_frozen_counter_blocks(self):
        engage()
        for _ in range(6):
            rx(0x394, counter=2)
        self.assertFalse(lib.safety_tx_hook(packet(0x4f1,data(0x4f1,button=2))))

    def test_steering_limits_are_enforced_for_porter(self):
        engage()
        excessive = ((1024+1000) << 16 | (1 << 27)).to_bytes(8,'little')
        self.assertFalse(lib.safety_tx_hook(packet(0x340,excessive)))

    def test_brake_release_does_not_auto_reenable(self):
        engage()
        rx(0x394, brake=True, counter=3)
        rx(0x394, brake=False, counter=4)
        rx(0x371, target=31)
        self.assertFalse(lib.get_controls_allowed())
        self.assertFalse(lib.safety_tx_hook(packet(0x4f1,data(0x4f1,button=1))))

    def test_other_hyundai_mode_still_expects_scc(self):
        lib.set_safety_hooks(8,1)
        lib.init_tests()
        lib.set_timer(1000)
        seed(button=2,target=50)
        self.assertFalse(lib.safety_config_valid())
        self.assertFalse(lib.get_controls_allowed())


if __name__=='__main__':unittest.main()
