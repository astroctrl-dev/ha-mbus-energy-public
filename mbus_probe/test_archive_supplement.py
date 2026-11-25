import unittest
from copy import deepcopy
from datetime import date
from history_model import build_snapshot
from archive_supplement import supplement_month

class ArchiveSupplementTests(unittest.TestCase):
    def setUp(self):
        self.saved = build_snapshot([{"month_back": n, "value": 1000-n,
            "unit": "kWh"} for n in range(1,25)], "2026-11-25T10:00:00Z",
            estimated_month=date(2026,11,1))
        self.archive = {"storage":2,"month_back":1,"cumulative_kwh":999,
            "cumulative_m3":0.0,"meter_storage_local_time":"2026-11-01T00:00",
            "maxima":{"power":{"value":12.0,"unit":"kW","meter_local_time":None}}}
        self.stamp = "2026-11-25T11:00:00Z"

    def test_preserves_energy_and_supplements_missing(self):
        original = deepcopy(self.saved)
        new = supplement_month(self.saved,self.archive,self.stamp)
        self.assertEqual(self.saved,original)
        self.assertEqual([{k:v for k,v in p.items() if k != "group_updated_at_utc"} for p in new["bounded_periods"]],original["bounded_periods"])
        self.assertTrue(all(p["group_updated_at_utc"] == "2026-11-25T11:00:00+00:00" for p in new["bounded_periods"]))
        self.assertEqual(supplement_month(new,self.archive,"2026-11-26T11:00:00Z"),new)
        self.assertEqual(new["stands"][1:],original["stands"][1:])
        evidence = new["stands"][0]["frame4"]
        self.assertEqual(evidence["cumulative_m3"],0.0)
        self.archive["maxima"]["power"]["meter_local_time"]="2026-10-31T12:00"
        later = supplement_month(new,self.archive,"2026-11-26T11:00:00Z")
        self.assertTrue(all(p["group_updated_at_utc"] == "2026-11-26T11:00:00+00:00" for p in later["bounded_periods"]))
        self.assertEqual(later["stands"][0]["frame4"]["first_read_at_utc"],
                         evidence["first_read_at_utc"])
        self.assertEqual(later["stands"][0]["frame4"]["maxima"]["power"]["meter_local_time"],
                         "2026-10-31T12:00")

    def test_conflict_does_not_mutate(self):
        new = supplement_month(self.saved,self.archive,self.stamp)
        old = deepcopy(new)
        self.archive["cumulative_m3"]=1.0
        with self.assertRaises(ValueError):
            supplement_month(new,self.archive,self.stamp)
        self.assertEqual(new,old)

    def test_alignment_required(self):
        for field,value in (("cumulative_kwh",998),("meter_storage_local_time","2026-10-01T00:00")):
            with self.assertRaises(ValueError):
                supplement_month(self.saved,{**self.archive,field:value},self.stamp)

    def test_individual_maximum_read_provenance(self):
        first = supplement_month(self.saved,self.archive,self.stamp)
        self.archive["maxima"]["flow"] = {"value":0.0,"unit":"m3/h",
            "meter_local_time":"2026-10-30T12:00"}
        self.archive["maxima"]["power"]["meter_local_time"]="2026-10-31T12:00"
        second = supplement_month(first,self.archive,"2026-11-26T11:00:00Z")
        maxima = second["stands"][0]["frame4"]["maxima"]
        self.assertEqual(maxima["power"]["read_at_utc"],"2026-11-25T11:00:00+00:00")
        self.assertEqual(maxima["power"]["meter_local_time_read_at_utc"],"2026-11-26T11:00:00+00:00")
        self.assertEqual(maxima["flow"]["read_at_utc"],"2026-11-26T11:00:00+00:00")
        self.assertEqual(supplement_month(second,self.archive,"2026-11-27T11:00:00Z"),second)
