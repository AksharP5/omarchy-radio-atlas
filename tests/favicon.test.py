#!/usr/bin/env python3

import importlib.machinery
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

        def curl(url, host, port, addresses, output):
            calls.append((url, addresses))
            return 302, "http://internal.example/secret.png"

        def getaddrinfo(host, port, **_):
            return resolve(answers[host])

        with (
            patch.object(proxy.socket, "getaddrinfo", side_effect=getaddrinfo),
            patch.object(proxy, "route_is_local", return_value=False),
        ):
            with self.assertRaises(radio_favicon.FaviconError):
                radio_favicon.fetch("http://icons.example/a.png", self.target, curl=curl)
        self.assertEqual(calls, [("http://icons.example/a.png", ["93.184.216.34"])])
        self.assertFalse(Path(self.target).exists())

    def test_public_image_is_saved_with_pinned_address(self):
        png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000004000000040806000000a9f19e7e0000001249444154789c63f8dfc0f01f1933902e0000504f27e1eb00f8a50000000049454e44ae426082")

        def curl(url, host, port, addresses, output):
            self.assertEqual((host, port, addresses), ("icons.example", 443, ["93.184.216.34"]))
            Path(output).write_bytes(png)
            return 200, ""

        with (
            patch.object(proxy.socket, "getaddrinfo", return_value=resolve("93.184.216.34")),
            patch.object(proxy, "route_is_local", return_value=False),
        ):
            radio_favicon.fetch("https://icons.example/a.png", self.target, curl=curl)
        self.assertEqual(Path(self.target).read_bytes(), png)

    def test_download_uses_reachable_address_after_the_first_connection_fails(self):
        image = b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>'
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(image)
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            # Stub validation only: curl really tries a refused IPv6 address,
            # then the IPv4 image server, without contacting public hosts.
            with patch.object(proxy, "public_endpoints", return_value=[
                    (socket.AF_INET6, socket.SOCK_STREAM, 6, ("::1", server.server_port, 0, 0)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, ("127.0.0.1", server.server_port))]):
                radio_favicon.fetch(f"http://icons.example:{server.server_port}/image.svg", self.target)
            self.assertEqual(Path(self.target).read_bytes(), image)
            self.assertEqual(requests, ["/image.svg"])
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_non_image_payload_is_discarded(self):
        def curl(url, host, port, addresses, output):
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

    def test_curl_config_cannot_follow_redirects_without_validation(self):
        image = b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>'
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/private.svg")
                else:
                    self.send_response(200)
                self.end_headers()
                if self.path != "/redirect":
                    self.wfile.write(image)

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        public_endpoints = proxy.public_endpoints

        def endpoints(host, port, **kwargs):
            if host == "icons.example":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, ("127.0.0.1", port))]
            return public_endpoints(host, port, **kwargs)

        Path(self.directory.name, ".curlrc").write_text("location\n")
        try:
            # Only the initial host is mapped to the fixture. Redirects must
            # still go through the real public-destination checks.
            with (
                patch.dict(os.environ, {"CURL_HOME": self.directory.name}),
                patch.object(proxy, "public_endpoints", side_effect=endpoints),
            ):
                with self.assertRaises(radio_favicon.FaviconError):
                    radio_favicon.fetch(f"http://icons.example:{server.server_port}/redirect", self.target)
            self.assertEqual(requests, ["/redirect"])
            self.assertFalse(Path(self.target).exists())
            self.assertEqual(list(Path(self.directory.name).glob(".favicon.*")), [])
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_encoded_hostnames_are_rejected_before_resolution(self):
        for host in ("%31%32%37.%30.%30.%31", "％３１％３２％３７．％３０．％３０．％３１"):
            with self.subTest(host=host), patch.object(proxy.socket, "getaddrinfo") as resolve_host:
                with self.assertRaises(radio_favicon.FaviconError):
                    radio_favicon.validated_hop(f"http://{host}/private.png")
            resolve_host.assert_not_called()

    def test_fake_ip_opt_in_applies_to_every_redirect(self):
        calls = []
        def curl(url, host, port, addresses, output):
            calls.append((url, addresses))
            if len(calls) == 1:
                return 302, "https://redirect.example/image.svg"
            Path(output).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>')
            return 200, ""
        with (
            patch.object(proxy.socket, "getaddrinfo", return_value=resolve("198.18.1.2")),
            patch.object(proxy, "route_is_local", return_value=False),
        ):
            with self.assertRaises(radio_favicon.FaviconError):
                radio_favicon.fetch("https://icons.example/image.svg", self.target, curl=curl)
            self.assertEqual(calls, [])
            radio_favicon.fetch("https://icons.example/image.svg", self.target, curl=curl, allow_fake_ip=True)
        self.assertEqual(len(calls), 2)
        self.assertEqual([addresses for _, addresses in calls], [["198.18.1.2"], ["198.18.1.2"]])

    def test_fake_ip_opt_in_still_rejects_private_redirects_and_local_routes(self):
        for address, local in [("127.0.0.1", False), ("10.0.0.1", False), ("198.18.1.2", True)]:
            with self.subTest(address=address), patch.object(
                proxy.socket, "getaddrinfo", return_value=resolve(address)), patch.object(
                proxy, "route_is_local", return_value=local):
                curl = Mock()
                with self.assertRaises(radio_favicon.FaviconError):
                    radio_favicon.fetch("https://icons.example/image.svg", self.target, curl=curl, allow_fake_ip=True)
                curl.assert_not_called()

    def test_unicode_hostname_is_canonical_before_validation_and_fetch(self):
        with patch.object(proxy, "public_endpoints", return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, ("93.184.216.34", 80))]) as endpoints:
            url, host, port, addresses = radio_favicon.validated_hop("https://bücher.example/image.svg")
        self.assertEqual((url, host, port, addresses),
                         ("https://xn--bcher-kva.example/image.svg", "xn--bcher-kva.example", 443, ["93.184.216.34"]))
        endpoints.assert_called_once_with(host, port, allow_fake_ip=False)

    def test_ipv6_literal_is_pinned_with_brackets(self):
        with patch.object(radio_favicon.subprocess, "run", return_value=Mock(returncode=0, stdout="200 ")) as run:
            radio_favicon.run_curl("https://[2001:4860:4860::8888]/image.svg", "2001:4860:4860::8888",
                                  443, ["2001:4860:4860::8888"], self.target)
        command = run.call_args.args[0]
        self.assertIn("--globoff", command, "Curl must not expand the URL after destination validation")
        self.assertEqual(command[command.index("--resolve") + 1],
                         "[2001:4860:4860::8888]:443:[2001:4860:4860::8888]")

    def test_overlapping_fetches_use_independent_temporary_files(self):
        image = '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>'
        outputs = []
        def curl(url, host, port, addresses, output):
            outputs.append(output)
            if len(outputs) == 1:
                radio_favicon.fetch(url, self.target, curl=curl)
            Path(output).write_text(image)
            return 200, ""
        with patch.object(proxy, "public_endpoints", return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, ("93.184.216.34", 80))]):
            radio_favicon.fetch("https://icons.example/image.svg", self.target, curl=curl)
        self.assertNotEqual(outputs[0], outputs[1])
        self.assertEqual(Path(self.target).read_text(), image)
        self.assertEqual(list(Path(self.target).parent.iterdir()), [Path(self.target)])

    def test_non_public_fallback_address_rejects_the_whole_download(self):
        curl = Mock()
        with (
            patch.object(proxy.socket, "getaddrinfo", return_value=resolve("93.184.216.34") + resolve("127.0.0.1")),
            patch.object(proxy, "route_is_local", return_value=False),
        ):
            with self.assertRaises(radio_favicon.FaviconError):
                radio_favicon.fetch("https://icons.example/image.svg", self.target, curl=curl)
        curl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
