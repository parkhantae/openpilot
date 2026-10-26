import unittest
from inspect_porter_log import decode_candidate


class TestCandidateDecoder(unittest.TestCase):
    def test_confirmed_fifty_and_cancel_encoding(self):
        self.assertEqual(decode_candidate(0x371, (50 << 23).to_bytes(8, 'little'))['set_speed_candidate'], 50)
        self.assertEqual(decode_candidate(0x371, bytes(8))['set_speed_candidate'], 0)

    def test_target_straddles_byte_boundary(self):
        # Test extraction only; these fixtures do not establish vehicle semantics.
        for value in (1, 49, 51, 160, 255):
            payload = ((value << 23) | ((1 << 23) - 1) | (0xff << 31)).to_bytes(8, 'little')
            self.assertEqual(decode_candidate(0x371, payload)['set_speed_candidate'], value)

    def test_limit_status_is_independent_of_target(self):
        for status in (0, 1):
            result = decode_candidate(0x371, ((50 << 23) | (status << 13)).to_bytes(8, 'little'))
            self.assertEqual(result['limit_status_candidate'], status)
            self.assertEqual(result['set_speed_candidate'], 50)
            self.assertNotIn('enabled', result)

    def test_brake_and_parking_are_independent(self):
        for override in range(4):
            for braking in (0, 1):
                for parking in (0, 1):
                    payload = ((override << 45) | (braking << 55) | (parking << 53)).to_bytes(8, 'little')
                    self.assertEqual(decode_candidate(0x394, payload), {
                        'driver_override': override, 'driver_braking': braking, 'parking_brake': parking})

    def test_buttons_and_main_are_independent(self):
        for button in range(8):
            for main in (0, 1):
                self.assertEqual(decode_candidate(0x4f1, bytes([button | (main << 3), 0, 0, 0])),
                                 {'cruise_button': button, 'main_button': main})

    def test_invalid_lengths_and_unknown_address(self):
        for address, expected in ((0x371, 8), (0x394, 8), (0x4f1, 4)):
            for size in (0, expected - 1, expected + 1):
                self.assertEqual(decode_candidate(address, bytes(size)), {})
        self.assertEqual(decode_candidate(0x999, bytes(8)), {})


if __name__ == '__main__':
    unittest.main()
