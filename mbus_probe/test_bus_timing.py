import tempfile
import unittest
from pathlib import Path
from bus_timing import BusTiming


class TimingTests(unittest.TestCase):
    def test_all_writers_share_interval_and_failed_send_counts(self):
        now = [0.]
        stamps = []
        def sleep(seconds):
            now[0] += seconds
        class Serial:
            def write(self, frame):
                stamps.append(now[0])
                if frame == b"fail":
                    raise OSError("test")
                return len(frame)
        with tempfile.TemporaryDirectory() as root:
            gate = BusTiming(Path(root) / "last", lambda: now[0],
                             lambda: 1000 + now[0], sleep)
            self.assertEqual(gate.write(Serial(), b"poll"), 4)
            with self.assertRaises(OSError):
                gate.write(Serial(), b"fail")
            gate.write(Serial(), b"restore")
            self.assertEqual(stamps, [60., 120., 180.])
            restarted = BusTiming(Path(root) / "last", lambda: now[0],
                                  lambda: 1000 + now[0], sleep)
            restarted.write(Serial(), b"poll")
            self.assertEqual(stamps[-1], 240.)


    def test_deferred_frame_is_built_after_gate_wait(self):
        now = [0.]
        built = []
        class Serial:
            def write(self, frame):
                return len(frame)
        with tempfile.TemporaryDirectory() as root:
            gate = BusTiming(Path(root) / "last", lambda: now[0],
                             lambda: 1000 + now[0],
                             lambda delay: now.__setitem__(0, now[0] + delay))
            self.assertFalse(gate.ready())
            def build():
                built.append(now[0])
                return b"clock"
            gate.write(Serial(), build)
            self.assertEqual(built, [60.])
            self.assertFalse(gate.ready())


    def test_expired_slot_does_not_send_or_advance_gate(self):
        from bus_timing import MissedSlot, poll_slot
        now = [0.]
        class Serial:
            def write(self, frame):
                raise AssertionError("expired slot must never send")
        with tempfile.TemporaryDirectory() as root:
            gate = BusTiming(Path(root) / "last", lambda: now[0],
                             lambda: 1000 + now[0],
                             lambda delay: now.__setitem__(0, now[0] + delay))
            with poll_slot(1000):
                with self.assertRaises(MissedSlot):
                    gate.write(Serial(), b"poll")
            now[0] = 62
            with poll_slot(1060):
                with self.assertRaises(MissedSlot):
                    gate.write(Serial(), b"poll")
            self.assertTrue(gate.ready())


    def test_runtime_read_and_direct_write_share_gate(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        from bus_timing import install_bus_timing, write_frame
        from mbus_probe import read_one
        now = [0.]
        stamps = []
        class Serial:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def reset_input_buffer(self): pass
            def flush(self): pass
            def read(self, count): return b""
            def write(self, frame):
                stamps.append(now[0])
                return len(frame)
        with tempfile.TemporaryDirectory() as root:
            gate = BusTiming(Path(root) / "last", lambda: now[0],
                             lambda: 1000 + now[0],
                             lambda delay: now.__setitem__(0, now[0] + delay))
            install_bus_timing(gate)
            try:
                with patch.dict(sys.modules, {"serial": SimpleNamespace(
                        Serial=lambda *a, **k: Serial())}):
                    read_one("/dev/test", 2400, 0, 2)
                    write_frame(Serial(), b"restore")
                    read_one("/dev/test", 2400, 0, 2)
                self.assertEqual(stamps, [60., 120., 180.])
            finally:
                install_bus_timing(None)

    def test_capture_runs_after_gate_release_and_eligibility_update(self):
        from unittest.mock import patch
        now = [0.]
        seen = []
        class Serial:
            def write(self, frame):
                if frame == b"fail":
                    raise OSError("test")
                return len(frame)
        with tempfile.TemporaryDirectory() as root:
            gate = BusTiming(Path(root) / "last", lambda: now[0],
                             lambda: 1000 + now[0],
                             lambda delay: now.__setitem__(0, now[0] + delay))
            def capture(direction, frame, status):
                seen.append((gate.lock.locked(), gate.eligible, now[0], status))
            with patch("bus_timing.capture", capture):
                self.assertEqual(gate.write(Serial(), b"ok"), 2)
                with self.assertRaises(OSError):
                    gate.write(Serial(), b"fail")
            self.assertEqual(seen, [(False, 120., 60., "sent"),
                                    (False, 180., 120., "write_error")])


class ResumeTests(unittest.TestCase):
    def test_fresh_restart_and_uncertain(self):
        now = [100.]
        stamps = []
        class Serial:
            def write(self, frame):
                stamps.append(now[0])
                return len(frame)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "last"
            def gate(**kw):
                return BusTiming(path, lambda: now[0], lambda: 1000 + now[0],
                                 lambda d: now.__setitem__(0, now[0]+d),
                                 resume=True, boot_id="test-boot", **kw)
            first = gate(fresh=True)
            first.write(Serial(), b"one")
            self.assertEqual(stamps, [100.])
            now[0] += 40
            restarted = gate()
            restarted.write(Serial(), b"two")
            self.assertEqual(stamps, [100., 160.])
            restarted._persist_resume(None)
            self.assertEqual(gate().eligible, 220.)
            now[0] += 80
            restarted._persist_resume(160.)
            self.assertTrue(gate().ready())


class SlotToleranceTests(unittest.TestCase):
    def test_flexible_slots_and_hour_boundary(self):
        from bus_timing import poll_slot, slot_tolerance, slot_open, MissedSlot
        self.assertTrue(slot_open(3595, 3598, slot_tolerance(True, 3595)))
        self.assertFalse(slot_open(3595, 3600, slot_tolerance(True, 3595)))
        self.assertTrue(slot_open(3600, 3609, slot_tolerance(False, 3600)))
        self.assertFalse(slot_open(3600, 3610, slot_tolerance(False, 3600)))
        now = [3500.]
        class Serial:
            def write(self, frame): return len(frame)
        with tempfile.TemporaryDirectory() as root:
            gate = BusTiming(Path(root)/"last", lambda: now[0], lambda: now[0],
                             lambda d: now.__setitem__(0, now[0]+d))
            now[0] = 3598.
            with poll_slot(3595., slot_tolerance(True, 3595.)):
                self.assertEqual(gate.write(Serial(), b"read"), 4)
            now[0] = 3600.
            with poll_slot(3595., slot_tolerance(True, 3595.)):
                with self.assertRaises(MissedSlot):
                    gate.write(Serial(), b"read")

    def test_durable_preparation_cannot_cross_hour_boundary(self):
        from bus_timing import poll_slot, slot_tolerance, MissedSlot
        from unittest.mock import patch
        now = [3500.]
        class Serial:
            def write(self, frame): raise AssertionError("must not transmit")
        with tempfile.TemporaryDirectory() as root:
            gate = BusTiming(Path(root)/"last", lambda: now[0], lambda: now[0],
                             lambda d: now.__setitem__(0, now[0]+d))
            now[0] = 3598.
            with patch.object(gate, "_persist_resume", side_effect=lambda _: now.__setitem__(0, 3600.)):
                with poll_slot(3595., slot_tolerance(True, 3595.)):
                    with self.assertRaises(MissedSlot):
                        gate.write(Serial(), b"read")

    def test_sixty_second_boundary(self):
        now = [0.]
        with tempfile.TemporaryDirectory() as root:
            gate = BusTiming(Path(root)/"last", lambda: now[0], lambda: now[0],
                             lambda d: now.__setitem__(0,now[0]+d))
            now[0] = 59.999
            self.assertFalse(gate.ready())
            now[0] = 60.
            self.assertTrue(gate.ready())

    def test_quiet_period_starts_after_serial_drain(self):
        now = [0.]
        starts = []
        class Serial:
            def write(self, frame):
                starts.append(now[0])
                return len(frame)
            def flush(self):
                now[0] += 0.05
        with tempfile.TemporaryDirectory() as root:
            gate = BusTiming(Path(root)/"last", lambda: now[0], lambda: now[0],
                             lambda d: now.__setitem__(0,now[0]+d))
            gate.write(Serial(),b"one")
            gate.write(Serial(),b"two")
            self.assertGreater(starts[1]-starts[0],60.)
            self.assertAlmostEqual(starts[1]-starts[0],60.05)
