import json
import tempfile
import unittest
from pathlib import Path
from raw_telegram_log import RawLog, classify, install, capture, operation, receive

class RawLogTests(unittest.TestCase):
    def test_capture_and_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            log=RawLog(tmp)
            install(log)
            try:
                capture("TX", b"abc", "sent")
                self.assertEqual(log.snapshot(), b"")
                log.set_enabled(True)
                @operation("history")
                @receive
                def response():
                    capture("TX", b"abc", "sent")
                    return b"\xe5"
                self.assertEqual(response(), b"\xe5")
                log.pending.join()
                rows=[json.loads(line) for line in log.snapshot().splitlines()]
                self.assertEqual([r["direction"] for r in rows], ["TX","RX"])
                self.assertEqual(rows[0]["transaction_id"], rows[1]["transaction_id"])
                self.assertEqual(rows[1]["operation"], "history")
                self.assertEqual(rows[1]["status"], "ack")
                log.set_enabled(False)
                capture("RX", b"", "timeout")
                self.assertEqual(len(log.snapshot().splitlines()), 2)
            finally:
                install(None)

    def test_rotation_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            log=RawLog(tmp, max_file=100)
            log.set_enabled(True)
            for i in range(12):
                log.offer({"hex":"a"*35,"index":i})
            log.pending.join()
            self.assertLessEqual(len(log.snapshot()),200)
            self.assertGreater(log.rotations,0)
            self.assertEqual(json.loads(log.snapshot().splitlines()[-1])["index"],11)
            self.assertEqual(classify(b""),"timeout")
            self.assertEqual(classify(b"\x68"),"invalid_or_partial")
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"file"
            path.touch()
            log=RawLog(path)
            log.set_enabled(True)
            log.offer({"hex":"ab"})
            log.pending.join()
            self.assertTrue(log.error)
            self.assertEqual(log.dropped,1)
