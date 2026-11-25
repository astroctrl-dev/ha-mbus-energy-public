import unittest
from mbus_records import decode_records
from maxima import project_maxima

class MaximaTests(unittest.TestCase):
    def project(self, body, frame="01"):
        return project_maxima({"records": decode_records(bytes.fromhex(
            body + " 0f 12 07 00 62 " + frame))})

    def test_observed_fields(self):
        m = self.project("9b 10 2d 20 01 00 9b 10 3b 52 11 00 "
                         "9b 10 5a 12 05 00 9b 10 5e 16 05 00 "
                         "94 10 ad 6f 00 0b 92 29 "
                         "94 10 bb 6f 2d 09 fd 14 "
                         "94 10 da 6f 38 10 13 31 "
                         "94 10 de 6f 36 10 13 31 "
                         "db 10 2d 20 01 00")
        self.assertEqual(m["power"]["maximum"], 12.0)
        self.assertEqual(m["flow"]["maximum"], 1.152)
        self.assertEqual(m["flow_temperature"]["maximum"], 51.2)
        self.assertEqual(m["return_temperature"]["maximum"], 51.6)
        self.assertEqual(m["power"]["maximum_meter_local_time"], "2020-09-18T11:00")
        self.assertEqual(m["power"]["previous_annual_maximum"], 12.0)

    def test_duplicate_and_wrong_frame(self):
        record = "9b 10 2d 20 01 00"
        self.assertIsNone(self.project(record+" "+record)["power"]["maximum"])
        self.assertIsNone(self.project(record, "02")["power"]["maximum"])

    def test_invalid_time_preserves_value(self):
        m = self.project("9b 10 2d 20 01 00 94 10 ad 6f ff 00 00 00")
        self.assertEqual(m["power"]["maximum"], 12)
        self.assertIsNone(m["power"]["maximum_meter_local_time"])
