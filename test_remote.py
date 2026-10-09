"""WebSocket protocol checks without pressing keys on the desktop."""

import ctypes
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / "vendor"))

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed, InvalidStatus

import remote
import run


class RemoteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = remote.RemoteSession("test-secret")
        self.context = serve(self.session.handle, "127.0.0.1", 0, origins=[remote.PAGES_ORIGIN], max_size=512)
        self.server = await self.context.__aenter__()
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/ws"

    async def asyncTearDown(self):
        await self.context.__aexit__(None, None, None)

    async def pair(self, ws, token="test-secret"):
        await ws.send(json.dumps({"type": "start", "token": token}))
        return json.loads(await ws.recv())

    async def command(self, ws, action, request_id):
        await ws.send(json.dumps({"type": "command", "action": action, "id": request_id}))
        return json.loads(await ws.recv())

    async def test_pairing_and_every_key_mapping(self):
        with patch.object(remote, "send_keys") as send:
            async with connect(self.url, origin=remote.PAGES_ORIGIN) as ws:
                self.assertEqual(await self.pair(ws), {"type": "ready"})
                for number, (action, keys) in enumerate(remote.ACTION_KEYS.items()):
                    self.session.last_action_at = 0
                    response = await self.command(ws, action, f"action-{number}")
                    self.assertEqual(response, {"type": "ack", "id": f"action-{number}", "ok": True})
                    self.assertEqual(send.call_args.args[0], keys)
                self.assertEqual(send.call_count, 6)

    async def test_invalid_token_and_origin_are_rejected(self):
        with self.assertRaises(InvalidStatus):
            async with connect(self.url, origin="https://other.example"):
                pass
        async with connect(self.url, origin=remote.PAGES_ORIGIN) as ws:
            await ws.send(json.dumps({"type": "start", "token": "wrong"}))
            with self.assertRaises(ConnectionClosed) as closed:
                await ws.recv()
            self.assertEqual(closed.exception.rcvd.code, 4003)

    async def test_unknown_action_never_sends_keys(self):
        with patch.object(remote, "send_keys") as send:
            async with connect(self.url, origin=remote.PAGES_ORIGIN) as ws:
                await self.pair(ws)
                response = await self.command(ws, "delete_everything", "bad-1")
                self.assertFalse(response["ok"])
                send.assert_not_called()

    async def test_duplicate_id_is_acknowledged_once(self):
        with patch.object(remote, "send_keys") as send:
            async with connect(self.url, origin=remote.PAGES_ORIGIN) as ws:
                await self.pair(ws)
                self.assertTrue((await self.command(ws, "next", "same-id"))["ok"])
                duplicate = await self.command(ws, "next", "same-id")
                self.assertTrue(duplicate["duplicate"])
                send.assert_called_once_with((0x22,))

    async def test_reconnect_does_not_replay_old_command(self):
        with patch.object(remote, "send_keys") as send:
            async with connect(self.url, origin=remote.PAGES_ORIGIN) as first:
                await self.pair(first)
                self.assertTrue((await self.command(first, "previous", "persist-id"))["ok"])
            async with connect(self.url, origin=remote.PAGES_ORIGIN) as second:
                self.assertEqual(await self.pair(second), {"type": "ready"})
                self.assertTrue((await self.command(second, "previous", "persist-id"))["duplicate"])
                send.assert_called_once_with((0x21,))

    async def test_new_phone_replaces_old_phone(self):
        async with connect(self.url, origin=remote.PAGES_ORIGIN) as first:
            await self.pair(first)
            async with connect(self.url, origin=remote.PAGES_ORIGIN) as second:
                self.assertEqual(await self.pair(second), {"type": "ready"})
                with self.assertRaises(ConnectionClosed) as closed:
                    await first.recv()
                self.assertEqual(closed.exception.rcvd.code, 4001)

    def test_windows_input_structure_has_full_union_size(self):
        self.assertEqual(ctypes.sizeof(remote.INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_setup_page_contains_private_hosted_link(self):
        with patch.object(run, "_public_url", "https://sample.trycloudflare.com"):
            page = run.setup_page().decode()
        self.assertIn(run.PAGES_URL, page)
        self.assertIn("https%3A%2F%2Fsample.trycloudflare.com", page)
        self.assertIn("data:image/svg+xml;base64,", page)
        self.assertNotIn("Bluetooth backup", page)


if __name__ == "__main__":
    unittest.main()
