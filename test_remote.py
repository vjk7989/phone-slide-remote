"""Checks command authentication and one-keypress behavior without touching the desktop."""

import http.client
import json
import threading
import unittest
import ctypes
from unittest.mock import patch

import remote
import run


class RemoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = remote.ThreadingHTTPServer(("127.0.0.1", 0), remote.RemoteHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        remote._recent_ids.clear()
        remote._last_action_at = 0

    def request(self, method, path, body=None, token=None, content_type=None, origin=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {}
        if token is not None:
            headers["X-Remote-Token"] = token
        if content_type:
            headers["Content-Type"] = content_type
        if origin:
            headers["Origin"] = origin
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def command(self, action, request_id, token=None):
        return self.request("POST", "/command", json.dumps({"action": action, "id": request_id}),
                            token=token, content_type="application/json")

    def test_page_serves_without_token_but_health_does_not(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Slide remote", body)
        self.assertEqual(self.request("GET", "/health")[0], 403)
        self.assertEqual(self.request("GET", "/health", token=remote.TOKEN)[0], 200)
        self.assertEqual(self.request("GET", "/setup")[0], 404)

    def test_only_named_actions_are_sent(self):
        with patch.object(remote, "send_keys") as send:
            self.assertEqual(self.command("next", "n1", remote.TOKEN)[0], 200)
            send.assert_called_once_with((0x22,))
            self.assertEqual(self.command("delete_file", "n2", remote.TOKEN)[0], 400)
            send.assert_called_once()

    def test_token_is_required_and_duplicate_id_is_not_replayed(self):
        with patch.object(remote, "send_keys") as send:
            self.assertEqual(self.command("window", "w1", "wrong")[0], 403)
            self.assertEqual(self.command("window", "w1", remote.TOKEN)[0], 200)
            self.assertEqual(self.command("window", "w1", remote.TOKEN)[0], 200)
            send.assert_called_once_with((0x12, 0x09))

    def test_bad_json_is_rejected(self):
        with patch.object(remote, "send_keys") as send:
            self.assertEqual(self.request("POST", "/command", b"not json", remote.TOKEN, "application/json")[0], 400)
            self.assertEqual(self.request("POST", "/command", b"{}", remote.TOKEN, "text/plain")[0], 415)
            send.assert_not_called()

    def test_windows_input_structure_has_full_union_size(self):
        self.assertEqual(ctypes.sizeof(remote.INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_only_github_pages_origin_gets_cors(self):
        status, _ = self.request("OPTIONS", "/command", origin=remote.PAGES_ORIGIN)
        self.assertEqual(status, 204)
        self.assertEqual(self.request("OPTIONS", "/command", origin="https://other.example")[0], 403)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request("GET", "/health", headers={"Origin": remote.PAGES_ORIGIN, "X-Remote-Token": remote.TOKEN})
        response = connection.getresponse()
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"), remote.PAGES_ORIGIN)
        response.read()
        connection.close()

    def test_bluetooth_link_appears_when_adapter_has_address(self):
        with patch.object(run, "bluetooth_ip", return_value="192.168.44.2"), patch.object(run, "_public_url", "https://sample.trycloudflare.com"):
            page = run.setup_page().decode()
        self.assertIn("Bluetooth backup", page)
        self.assertIn("http://192.168.44.2:8765/#", page)
        self.assertIn(run.PAGES_URL, page)
        self.assertIn("https%3A%2F%2Fsample.trycloudflare.com", page)
        self.assertIn("data:image/svg+xml;base64,", page)


if __name__ == "__main__":
    unittest.main()
