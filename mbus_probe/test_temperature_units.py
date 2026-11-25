import unittest
from temperature_units import convert_temperature

class TemperatureTests(unittest.TestCase):
    def test_absolute(self):
        for kind in ("flow_temperature", "return_temperature"):
            for target, expected in (("C",37.5),("K",310.65),("F",99.5)):
                value, unit = convert_temperature(kind,37.5,"C",target)
                self.assertAlmostEqual(value,expected)
                self.assertAlmostEqual(convert_temperature(kind,value,target,"C")[0],37.5)

    def test_difference(self):
        for source, value in (("C",1.1),("K",1.1),("F",1.98)):
            for target, expected in (("C",1.1),("K",1.1),("F",1.98)):
                self.assertAlmostEqual(convert_temperature("temperature_difference",value,source,target)[0],expected)

    def test_other_measurements(self):
        self.assertEqual(convert_temperature("energy",123,"kWh","F"),(123,"kWh"))

    def test_invalid(self):
        for value in (float("nan"),float("inf"),True):
            with self.assertRaises(ValueError):
                convert_temperature("flow_temperature",value,"C","F")
