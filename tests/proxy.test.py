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
        with (
            patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve("93.184.216.34")),
            patch.object(radio_proxy, "route_is_local", return_value=False),
        ):
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
        with (
            patch.object(radio_proxy.socket, "getaddrinfo", return_value=answers),
            patch.object(radio_proxy, "route_is_local", return_value=False),
        ):
            with self.assertRaises(radio_proxy.ProxyError):
                radio_proxy.public_endpoints("station.example", 80)

    def test_excessive_dns_answers_are_rejected_before_route_checks(self):
        answers = self.resolve(*(f"93.184.216.{index}" for index in range(1, 18)))
        with (
            patch.object(radio_proxy.socket, "getaddrinfo", return_value=answers),
            patch.object(radio_proxy, "route_is_local", return_value=False) as route_check,
        ):
            with self.assertRaises(radio_proxy.ProxyError):
                radio_proxy.public_endpoints("station.example", 80)
        self.assertEqual(route_check.call_count, radio_proxy.MAX_RESOLVED_ENDPOINTS)

    def test_effectively_local_public_destination_is_rejected(self):
        with (
            patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve("2001:4860:4860::8888")),
            patch.object(radio_proxy, "route_is_local", return_value=True),
        ):
            with self.assertRaises(radio_proxy.ProxyError):
                radio_proxy.public_endpoints("station.example", 80)

    def test_kernel_local_route_is_detected(self):
        result = radio_proxy.subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b'[{"type":"local","dev":"lo"}]', stderr=b""
        )
        with patch.object(radio_proxy.subprocess, "run", return_value=result):
            self.assertTrue(radio_proxy.route_is_local(radio_proxy.ipaddress.ip_address("8.8.8.8")))

    def test_nat64_destination_with_private_ipv4_is_rejected(self):
        address = "64:ff9b::a00:1"
        self.assertTrue(radio_proxy.embeds_non_public_ipv4(radio_proxy.ipaddress.ip_address(address)))
        with patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve(address)):
            with self.assertRaises(radio_proxy.ProxyError):
                radio_proxy.public_endpoints("station.example", 80)

    def test_ipv4_compatible_loopback_is_rejected(self):
        address = "::127.0.0.1"
        self.assertTrue(radio_proxy.embeds_non_public_ipv4(radio_proxy.ipaddress.ip_address(address)))
        with patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve(address)):
            with self.assertRaises(radio_proxy.ProxyError):
                radio_proxy.public_endpoints("station.example", 80)

    def test_idle_relay_returns_after_timeout(self):
        with patch.object(radio_proxy.select, "select", return_value=([], [], [])) as select_call:
            radio_proxy.relay(object(), object())
        select_call.assert_called_once()

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
