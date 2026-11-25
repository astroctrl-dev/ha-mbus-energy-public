import unittest
from history_controller import HistoryController
from mbus_records import decode_records

class RecoveryArchiveTests(unittest.TestCase):
    def test_exact_identity_and_footer_required(self):
        header=dict(type="long",ci=0x72,control=8,address=1,meter_id="00000000",
                    manufacturer="LUG",medium_code=4,status=0,
                    records=decode_records(bytes.fromhex("0f 12 07 00 62 04")))
        check=HistoryController._confirmed_archive
        self.assertTrue(check(header,1,"00000000"))
        for field,value in (("address",2),("meter_id","00000001"),("status",1),
                            ("manufacturer","ABC"),("records",[])):
            self.assertFalse(check({**header,field:value},1,"00000000"))
