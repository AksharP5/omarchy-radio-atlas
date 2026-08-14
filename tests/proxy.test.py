#!/usr/bin/env python3

import importlib.machinery
import importlib.util
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
project_dir = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("radio_proxy", str(project_dir / "radio-proxy"))
spec = importlib.util.spec_from_loader(loader.name, loader)
radio_proxy = importlib.util.module_from_spec(spec)
loader.exec_module(radio_proxy)


class ProxyTests(unittest.TestCase):
    def resolve(self, *addresses):
        return [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))
            for address in addresses
        ]

    def test_only_public_destinations_are_returned(self):
        with patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve("93.184.216.34")):
            endpoints = radio_proxy.public_endpoints("fc-radio.example", 80)
        self.assertEqual(endpoints[0][3][0], "93.184.216.34")

    def test_non_public_destinations_are_rejected(self):
        addresses = (
            "127.0.0.1",
            "10.0.0.1",
            "169.254.1.1",
            "::1",
            "fd00::1",
            "fec0::1",
            "fe80::1",
        )
        for address in addresses:
            with self.subTest(address=address):
                with patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve(address)):
                    with self.assertRaises(radio_proxy.ProxyError):
                        radio_proxy.public_endpoints("station.example", 80)

    def test_mixed_dns_answers_are_rejected(self):
        answers = self.resolve("93.184.216.34", "192.168.1.10")
        with patch.object(radio_proxy.socket, "getaddrinfo", return_value=answers):
            with self.assertRaises(radio_proxy.ProxyError):
                radio_proxy.public_endpoints("station.example", 80)

    def test_plain_http_request_is_normalized(self):
        request = (
            b"GET http://example.com:8000/live?q=1 HTTP/1.1\r\n"
            b"Host: ignored.example\r\nProxy-Connection: keep-alive\r\nUser-Agent: Test\r\n\r\n"
        )
        method, host, port, forwarded = radio_proxy.parse_request(request)
        self.assertEqual((method, host, port), ("GET", "example.com", 8000))
        self.assertTrue(forwarded.startswith(b"GET /live?q=1 HTTP/1.1\r\n"))
        self.assertIn(b"Host: example.com:8000\r\n", forwarded)
        self.assertIn(b"Connection: close\r\n", forwarded)
        self.assertNotIn(b"ignored.example", forwarded)
        self.assertNotIn(b"Proxy-Connection", forwarded)


if __name__ == "__main__":
    unittest.main()
