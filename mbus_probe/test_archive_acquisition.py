import unittest
from unittest.mock import patch
from archive_acquisition import collect_one, select_archive
from monthly_diagnostic import RestorationError

class AcquisitionTests(unittest.TestCase):
    def test_selectors(self):
        for month, selector in ((1,b"\x31"),(15,b"\x3f"),(16,b"\x30\x01"),(24,b"\x38\x01")):
            tx=select_archive(1,month)
            self.assertEqual(tx[7:-2],selector)
            self.assertEqual(tx[-2],sum(tx[4:-2])&255)
    def test_approval(self):
        with self.assertRaises(ValueError):
            collect_one({},1,"00000000",1,lambda _:self.fail("unexpected I/O"))
    def test_restore_on_selection_failure(self):
        calls=[]
        def exchange(tx):
            calls.append(tx)
            return b"" if len(calls)==1 else b"\xe5"
        with patch("archive_acquisition.verify_normal_frame") as verify:
            with self.assertRaisesRegex(ValueError,"selection"):
                collect_one({},1,"00000000",1,exchange,approved=True)
            verify.assert_called_once()
        self.assertEqual(len(calls),3)
    def test_restore_failure_overrides_selection_failure(self):
        with self.assertRaises(RestorationError):
            collect_one({},1,"00000000",1,lambda _:b"",approved=True)
    def test_verified_transaction(self):
        header=dict(type="long",ci=0x72,control=8,address=1,meter_id="00000000",
                    manufacturer="LUG",medium_code=4,status=0)
        with patch("archive_acquisition.validate",return_value=header), \
             patch("archive_acquisition.decode_month",return_value={"archive":1}), \
             patch("archive_acquisition.verify_normal_frame") as verify, \
             patch("archive_acquisition.supplement_month",return_value={"saved":1}) as supplement:
            self.assertEqual(collect_one({},1,"00000000",1,lambda _:b"\xe5",approved=True),{"saved":1})
            verify.assert_called_once()
            supplement.assert_called_once()

    def test_conflict_after_normal_restore_is_data_error(self):
        from archive_acquisition import ArchiveDataError
        header=dict(type="long",ci=0x72,control=8,address=1,meter_id="00000000",
                    manufacturer="LUG",medium_code=4,status=0)
        with patch("archive_acquisition.validate",return_value=header), \
             patch("archive_acquisition.decode_month",return_value={}), \
             patch("archive_acquisition.verify_normal_frame") as verify, \
             patch("archive_acquisition.supplement_month",side_effect=ValueError("conflict")):
            with self.assertRaises(ArchiveDataError):
                collect_one({},1,"00000000",1,lambda _:b"\xe5",approved=True)
            verify.assert_called_once()
