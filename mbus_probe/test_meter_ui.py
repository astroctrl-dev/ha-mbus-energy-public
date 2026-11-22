import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from meter_registry import MeterRegistry
from meter_ui import serve


class IngressBoundaryTests(unittest.TestCase):
    def test_direct_container_request_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = MeterRegistry(Path(directory) / "meters.json")
            server = serve(registry, {"serial_port": "/dev/ttyUSB0"}, None,
                           threading.Lock(), threading.Event(), port=0)
            try:
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(f"http://127.0.0.1:{server.server_port}/api/meters")
                self.assertEqual(ctx.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
