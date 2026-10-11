#!/usr/bin/env python3

import importlib.machinery
import importlib.util
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
project_dir = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("radio_favicon", str(project_dir / "radio-favicon"))
spec = importlib.util.spec_from_loader(loader.name, loader)
radio_favicon = importlib.util.module_from_spec(spec)
loader.exec_module(radio_favicon)
proxy = radio_favicon.radio_proxy


def resolve(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, 80))]


class FaviconTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.target = str(Path(self.directory.name) / "icon")

    def tearDown(self):
        self.directory.cleanup()

    def test_loopback_and_private_hosts_are_rejected_before_download(self):
        for address in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "100.64.0.1", "::1", "fd00::1"):
            curl = unittest.mock.Mock()
            with patch.object(proxy.socket, "getaddrinfo", return_value=resolve(address)):
                with self.assertRaises(radio_favicon.FaviconError, msg=address):
                    radio_favicon.fetch("http://icons.example/a.png", self.target, curl=curl)
            curl.assert_not_called()

    def test_redirect_to_private_address_is_rejected(self):
        answers = {"icons.example": "93.184.216.34", "internal.example": "192.168.1.1"}
        calls = []

        def curl(url, host, port, address, output):
            calls.append((url, address))
            return 302, "http://internal.example/secret.png"

        def getaddrinfo(host, port, **_):
            return resolve(answers[host])

        with (
            patch.object(proxy.socket, "getaddrinfo", side_effect=getaddrinfo),
            patch.object(proxy, "route_is_local", return_value=False),
        ):
            with self.assertRaises(radio_favicon.FaviconError):
                radio_favicon.fetch("http://icons.example/a.png", self.target, curl=curl)
        self.assertEqual(calls, [("http://icons.example/a.png", "93.184.216.34")])
        self.assertFalse(Path(self.target).exists())

    def test_public_image_is_saved_with_pinned_address(self):
        png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000004000000040806000000a9f19e7e0000001249444154789c63f8dfc0f01f1933902e0000504f27e1eb00f8a50000000049454e44ae426082")

        def curl(url, host, port, address, output):
            self.assertEqual((host, port, address), ("icons.example", 443, "93.184.216.34"))
            Path(output).write_bytes(png)
            return 200, ""

        with (
            patch.object(proxy.socket, "getaddrinfo", return_value=resolve("93.184.216.34")),
            patch.object(proxy, "route_is_local", return_value=False),
        ):
            radio_favicon.fetch("https://icons.example/a.png", self.target, curl=curl)
        self.assertEqual(Path(self.target).read_bytes(), png)

    def test_non_image_payload_is_discarded(self):
        def curl(url, host, port, address, output):
            Path(output).write_text("<html>nope</html>")
            return 200, ""

        with (
            patch.object(proxy.socket, "getaddrinfo", return_value=resolve("93.184.216.34")),
            patch.object(proxy, "route_is_local", return_value=False),
        ):
            with self.assertRaises(radio_favicon.FaviconError):
                radio_favicon.fetch("http://icons.example/a.png", self.target, curl=curl)
        self.assertFalse(Path(self.target).exists())
        self.assertFalse(Path(self.target + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
