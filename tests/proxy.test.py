#!/usr/bin/env python3

import importlib.machinery
import importlib.util
import contextlib
import io
import errno
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

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

    def test_unavailable_address_family_does_not_prevent_ipv4_fallback(self):
        reachable = Mock()
        with (
            patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve(
                "2001:4860:4860::8888", "93.184.216.34")),
            patch.object(radio_proxy, "route_is_local", return_value=False),
            patch.object(radio_proxy.socket, "socket", side_effect=[
                OSError(errno.EAFNOSUPPORT, "Address family not supported"), reachable]),
        ):
            connected = radio_proxy.connect_public("station.example", 80)
        self.assertIs(connected, reachable)
        reachable.connect.assert_called_once_with(("93.184.216.34", 80))
        reachable.close.assert_not_called()

    def test_explicit_zero_port_is_rejected(self):
        for request in (b"GET http://station.example:0/live HTTP/1.1\r\n\r\n",
                        b"CONNECT station.example:0 HTTP/1.1\r\n\r\n"):
            with self.subTest(request=request):
                with self.assertRaises(radio_proxy.ProxyError) as error:
                    radio_proxy.parse_request(request)
                self.assertEqual(error.exception.status, b"400 Bad Request")

    def test_non_public_destinations_are_rejected(self):
        addresses = (
            "127.0.0.1",
            "10.0.0.1",
            "169.254.1.1",
            "::1",
            "fd00::1",
            "fec0::1",
            "fe80::1",
            "4000::1",
            "64:ff9b:1::808:808",
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

    def test_fake_ip_answers_cannot_connect_over_a_nonlocal_route(self):
        for address in ("198.18.0.0", "198.18.0.166", "198.19.255.255", "2001:2::110", "fdfe:dcba:9876::a2"):
            for answers in (self.resolve(address), self.resolve("93.184.216.34", address)):
                with (
                    self.subTest(answers=answers),
                    patch.object(radio_proxy.socket, "getaddrinfo", return_value=answers),
                    patch.object(radio_proxy, "route_is_local", return_value=False),
                    patch.object(radio_proxy.socket, "socket") as upstream,
                ):
                    with self.assertRaises(radio_proxy.ProxyError) as error:
                        radio_proxy.connect_public("station.example", 80)
                    self.assertEqual(error.exception.status, b"403 Forbidden")
                    upstream.assert_not_called()

    def test_fake_ip_opt_in_connects_to_the_validated_address(self):
        for address in ("198.18.0.0", "198.18.0.166", "198.19.255.255"):
            with (
                self.subTest(address=address),
                patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve(address)),
                patch.object(radio_proxy, "route_is_local", return_value=False) as route_check,
                patch.object(radio_proxy.socket, "socket") as upstream,
            ):
                connected = radio_proxy.connect_public("station.example", 80, allow_fake_ip=True)
                self.assertIs(connected, upstream.return_value)
                connected.connect.assert_called_once_with((address, 80))
                route_check.assert_called_once_with(radio_proxy.ipaddress.ip_address(address))

    def test_fake_ip_opt_in_rejects_mixed_non_public_answers_before_connecting(self):
        for address in (
            "0.0.0.0", "127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1",
            "169.254.169.254", "100.64.0.1", "192.0.2.1", "224.0.0.1", "240.0.0.1",
            "::", "::1", "fe80::1", "fec0::1", "fd00::1", "ff02::1", "4000::1",
            "2001:2::110", "fdfe:dcba:9876::a2", "::ffff:198.18.0.166",
            "64:ff9b::c612:a6", "::198.18.0.166", "2002:c612:a6::1",
            "2001:0:808:808:0:ffff:39ed:ff59", "64:ff9b::a00:1",
        ):
            with (
                self.subTest(address=address),
                patch.object(radio_proxy.socket, "getaddrinfo",
                             return_value=self.resolve("198.18.0.166", address)),
                patch.object(radio_proxy, "route_is_local", return_value=False),
                patch.object(radio_proxy.socket, "socket") as upstream,
            ):
                with self.assertRaises(radio_proxy.ProxyError) as error:
                    radio_proxy.connect_public("station.example", 80, allow_fake_ip=True)
                self.assertEqual(error.exception.status, b"403 Forbidden")
                upstream.assert_not_called()

    def test_fake_ip_opt_in_still_rejects_local_routes(self):
        with (
            patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve("198.18.0.166")),
            patch.object(radio_proxy, "route_is_local", return_value=True),
            patch.object(radio_proxy.socket, "socket") as upstream,
        ):
            with self.assertRaises(radio_proxy.ProxyError) as error:
                radio_proxy.connect_public("station.example", 80, allow_fake_ip=True)
            self.assertEqual(error.exception.status, b"403 Forbidden")
            upstream.assert_not_called()

    def test_http_and_connect_use_the_session_fake_ip_setting(self):
        for allow_fake_ip in (False, True):
            for method, target in (("GET", "http://station.example/live"), ("CONNECT", "station.example:80")):
                request = Mock()
                request.recv.return_value = f"{method} {target} HTTP/1.1\r\n\r\n".encode()
                with (
                    self.subTest(allow_fake_ip=allow_fake_ip, method=method),
                    patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve("198.18.0.166")),
                    patch.object(radio_proxy, "route_is_local", return_value=False),
                    patch.object(radio_proxy.socket, "socket", return_value=MagicMock()) as upstream,
                    patch.object(radio_proxy, "relay", return_value="upstream_closed"),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    radio_proxy.ProxyHandler(request, None, Mock(allow_fake_ip=allow_fake_ip))
                    if allow_fake_ip:
                        upstream.return_value.connect.assert_called_once_with(("198.18.0.166", 80))
                        if method == "CONNECT":
                            request.sendall.assert_called_once_with(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                        else:
                            forwarded = upstream.return_value.__enter__.return_value.sendall.call_args.args[0]
                            self.assertTrue(forwarded.startswith(b"GET /live HTTP/1.1\r\n"))
                    else:
                        upstream.assert_not_called()
                        self.assertIn(b"403 Forbidden", request.sendall.call_args.args[0])

    def test_alternate_numeric_fake_ip_hosts_are_rejected(self):
        # These are numeric addresses to libc, despite not parsing with ipaddress.
        for host in ("0xc61200a6", "198.18.166", "0306.022.0.0246"):
            for request in (f"GET http://{host}/live HTTP/1.1\r\n\r\n",
                            f"CONNECT {host}:443 HTTP/1.1\r\n\r\n"):
                with (
                    self.subTest(request=request),
                    patch.object(radio_proxy, "route_is_local", return_value=False),
                    patch.object(radio_proxy.socket, "socket") as upstream,
                ):
                    _, target, port, _ = radio_proxy.parse_request(request.encode())
                    with self.assertRaises(radio_proxy.ProxyError) as error:
                        radio_proxy.connect_public(target, port)
                    self.assertEqual(error.exception.status, b"403 Forbidden")
                    upstream.assert_not_called()

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
        for address in ("2001:4860:4860::8888", "64:ff9b::808:808"):
            with (
                self.subTest(address=address),
                patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve(address)),
                patch.object(radio_proxy, "route_is_local", return_value=True) as route_check,
            ):
                with self.assertRaises(radio_proxy.ProxyError):
                    radio_proxy.public_endpoints("station.example", 80)
                route_check.assert_called_once_with(radio_proxy.ipaddress.ip_address(address))

    def test_kernel_local_route_is_detected(self):
        result = radio_proxy.subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b'[{"type":"local","dev":"lo"}]', stderr=b""
        )
        with patch.object(radio_proxy.subprocess, "run", return_value=result):
            self.assertTrue(radio_proxy.route_is_local(radio_proxy.ipaddress.ip_address("8.8.8.8")))

    def test_public_dns64_destinations_are_returned(self):
        for addresses in (
            ("64:ff9b::c127:db2",),
            ("193.39.13.178", "64:ff9b::c127:db2"),
        ):
            with (
                self.subTest(addresses=addresses),
                patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve(*addresses)),
                patch.object(radio_proxy, "route_is_local", return_value=False),
            ):
                endpoints = radio_proxy.public_endpoints("station.example", 80)
                self.assertEqual([endpoint[3][0] for endpoint in endpoints], list(addresses))

    def test_nat64_destination_with_non_public_ipv4_is_rejected(self):
        for ipv4 in ("10.0.0.1", "127.0.0.1", "169.254.169.254", "100.64.0.1", "224.0.0.1"):
            address = str(radio_proxy.ipaddress.IPv6Address(
                int(radio_proxy.NAT64_WELL_KNOWN.network_address)
                | int(radio_proxy.ipaddress.IPv4Address(ipv4))))
            with (
                self.subTest(ipv4=ipv4),
                patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve("8.8.8.8", address)),
                patch.object(radio_proxy, "route_is_local", return_value=False),
            ):
                with self.assertRaises(radio_proxy.ProxyError) as error:
                    radio_proxy.public_endpoints("station.example", 80)
                self.assertEqual(error.exception.status, b"403 Forbidden")

    def test_ipv4_compatible_loopback_is_rejected(self):
        address = "::127.0.0.1"
        self.assertTrue(radio_proxy.embeds_non_public_ipv4(radio_proxy.ipaddress.ip_address(address)))
        with patch.object(radio_proxy.socket, "getaddrinfo", return_value=self.resolve(address)):
            with self.assertRaises(radio_proxy.ProxyError):
                radio_proxy.public_endpoints("station.example", 80)

    def test_idle_relay_returns_after_timeout(self):
        with patch.object(radio_proxy.select, "select", return_value=([], [], [])) as select_call:
            self.assertEqual(radio_proxy.relay(object(), object()), "idle_timeout")
        select_call.assert_called_once()

    def test_relay_identifies_which_side_closed(self):
        client, upstream = Mock(), Mock()
        for source, outcome in ((client, "client_closed"), (upstream, "upstream_closed")):
            source.recv.return_value = b""
            with patch.object(radio_proxy.select, "select", return_value=([source], [], [])):
                self.assertEqual(radio_proxy.relay(client, upstream), outcome)

    def test_connection_failure_logs_stage_without_remote_data(self):
        output = io.StringIO()
        request = Mock()
        failure = radio_proxy.ProxyError(b"502 Bad Gateway")
        failure.__cause__ = socket.gaierror(-2, "https://private.example/live?token=secret\nforged log")
        with (
            patch.object(radio_proxy, "diagnostic_count", 0),
            patch.object(radio_proxy, "read_header", return_value=(b"header", b"")),
            patch.object(radio_proxy, "parse_request", return_value=("CONNECT", "private.example", 443, b"")),
            patch.object(radio_proxy, "connect_public", side_effect=failure),
            contextlib.redirect_stderr(output),
        ):
            radio_proxy.ProxyHandler(request, None, Mock(allow_fake_ip=False))
        self.assertEqual(output.getvalue(),
                         "radio-proxy: stage=connect outcome=rejected error=ProxyError status=502 cause=gaierror errno=-2\n")
        request.sendall.assert_called_once_with(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")

    def test_relay_exception_is_logged_and_diagnostics_are_bounded(self):
        output = io.StringIO()
        request = Mock()
        upstream = Mock()
        upstream.__enter__ = Mock(return_value=upstream)
        upstream.__exit__ = Mock(return_value=False)
        with (
            patch.object(radio_proxy, "diagnostic_count", 0),
            patch.object(radio_proxy, "read_header", return_value=(b"header", b"")),
            patch.object(radio_proxy, "parse_request", return_value=("CONNECT", "private.example", 443, b"")),
            patch.object(radio_proxy, "connect_public", return_value=upstream),
            patch.object(radio_proxy, "relay", side_effect=TimeoutError("secret stream URL")),
            contextlib.redirect_stderr(output),
        ):
            for _ in range(radio_proxy.MAX_DIAGNOSTICS + 2):
                radio_proxy.ProxyHandler(request, None, Mock(allow_fake_ip=False))
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), radio_proxy.MAX_DIAGNOSTICS)
        self.assertEqual(lines[0], "radio-proxy: stage=relay outcome=failed error=TimeoutError")
        self.assertEqual(lines[-1], "radio-proxy: diagnostic limit reached for this session")
        self.assertNotIn("secret", output.getvalue())

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
