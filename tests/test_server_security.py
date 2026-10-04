"""No model weights, GPU, HTTP server or real network are needed for these tests."""

import asyncio
import importlib.util
import pathlib
import socket
import unittest
from unittest.mock import AsyncMock, patch

spec = importlib.util.spec_from_file_location(
    "server_security", pathlib.Path(__file__).parents[1] / "rembg/server_security.py"
)
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)


class URLBoundaryTest(unittest.TestCase):
    def test_private_protocols_addresses_and_userinfo_are_rejected(self):
        for url in [
            "file:///etc/passwd",
            "http://127.0.0.1/",
            "http://169.254.169.254/",
            "http://192.168.1.1/",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",
            "http://[64:ff9b::7f00:1]/",
            "http://[2002:7f00:1::]/",
            "http://224.0.0.1/",
            "http://239.255.255.250/",
            "http://[ff02::1]/",
            "http://[ff01::1]/",
            "http://[fec0::1]/",
            "https://user:pass@example.org/",
            "https://example.org:8443/",
            "https://localhost/",
            "http://example.org\\@127.0.0.1/",
        ]:
            with self.subTest(url=url), self.assertRaises(security.HTTPException):
                security.public_url(url)
        self.assertEqual(
            security.public_url("https://example.org/image.png"),
            "https://example.org/image.png",
        )

    def test_http_options_never_select_local_files_or_python_providers(self):
        for options in [
            '{"model_path":"/tmp/fixture"}',
            '{"providers":["fixture"]}',
            "[]",
            "{broken",
            '{"prompt":[],"unknown":true}',
            '{"putalpha":"yes"}',
            '{"cc":[]}',
            '{"prompt":{}}',
            "[" * 1500 + "]" * 1500,
        ]:
            with self.subTest(options=options), self.assertRaises(
                security.HTTPException
            ):
                security.server_options(options)
        self.assertEqual(
            security.server_options('{"putalpha":true}'), {"putalpha": True}
        )


class AsyncBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_dns_rejects_mixed_and_private_answers_without_a_second_resolution(
        self,
    ):
        public = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        private = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        loop = asyncio.get_running_loop()
        with patch.object(
            loop, "getaddrinfo", new=AsyncMock(return_value=[public, private])
        ):
            with self.assertRaises(OSError):
                await security.PublicResolver().resolve("example.org", 443)
        with patch.object(
            loop, "getaddrinfo", new=AsyncMock(return_value=[public])
        ) as dns:
            results = await security.PublicResolver().resolve("example.org", 443)
        self.assertEqual(results[0]["host"], "8.8.8.8")
        self.assertEqual(results[0]["flags"], socket.AI_NUMERICHOST)
        dns.assert_awaited_once()

    async def test_chunked_body_limit_runs_before_application(self):
        app = AsyncMock()
        receive = AsyncMock(
            side_effect=[
                {"type": "http.request", "body": b"123", "more_body": True},
                {"type": "http.request", "body": b"456", "more_body": False},
            ]
        )
        send = AsyncMock()
        await security.RequestSizeLimit(app, limit=5)({"type": "http"}, receive, send)
        app.assert_not_awaited()
        self.assertEqual(send.await_args_list[0].args[0]["status"], 413)

    async def test_bounded_body_is_replayed_without_content_loss(self):
        bodies = []

        async def app(scope, receive, send):
            while True:
                msg = await receive()
                bodies.append(msg["body"])
                if not msg.get("more_body", False):
                    return

        receive = AsyncMock(
            side_effect=[
                {"type": "http.request", "body": b"12", "more_body": True},
                {"type": "http.request", "body": b"345", "more_body": False},
            ]
        )
        await security.RequestSizeLimit(app, limit=5)(
            {"type": "http"}, receive, AsyncMock()
        )
        self.assertEqual(b"".join(bodies), b"12345")

    async def test_slow_body_is_rejected_without_processing(self):
        async def receive():
            await asyncio.sleep(1)

        app, send = AsyncMock(), AsyncMock()
        await security.RequestSizeLimit(app, timeout=0.001)(
            {"type": "http"}, receive, send
        )
        app.assert_not_awaited()
        self.assertEqual(send.await_args_list[0].args[0]["status"], 408)

    async def test_redirect_is_revalidated_and_large_stream_is_rejected(self):
        class Response:
            def __init__(self, status, location=None, chunks=(), length=None):
                self.status, self.content_length = status, length
                self.headers = {"Location": location} if location else {}
                self.content = self
                self.chunks = chunks

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def iter_chunked(self, size):
                for c in self.chunks:
                    yield c

        class Client:
            def __init__(self, responses):
                self.responses, self.calls = list(responses), []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return self.responses.pop(0)

        client = Client([Response(302, "http://127.0.0.1/")])
        with patch.object(security.aiohttp, "ClientSession", return_value=client):
            with self.assertRaises(security.HTTPException) as context:
                await security.fetch_image("https://example.org/image")
        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(len(client.calls), 1)
        self.assertFalse(client.calls[0][1]["allow_redirects"])
        client = Client([Response(200, chunks=[b"12", b"3456"])])
        with patch.object(
            security.aiohttp, "ClientSession", return_value=client
        ), patch.object(security, "MAX_IMAGE_BYTES", 5):
            with self.assertRaises(security.HTTPException) as context:
                await security.fetch_image("https://example.org/image")
        self.assertEqual(context.exception.status_code, 413)
