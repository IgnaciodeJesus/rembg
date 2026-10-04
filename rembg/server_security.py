"""Bound network and request input before any model or image processing.

These controls apply to the optional HTTP server. Local CLI files and custom
models remain available to a trusted local caller.
"""

import asyncio
import ipaddress
import json
import socket
import time
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from fastapi import HTTPException

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_REQUEST_BYTES = 12 * 1024 * 1024


def is_public(address):
    ip = ipaddress.ip_address(address)
    if (
        not ip.is_global
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
        or ip.is_loopback
        or ip.is_link_local
        or getattr(ip, "ipv4_mapped", None)
    ):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.is_site_local:
            return False
        # Translation/tunnel forms can disguise a non-public IPv4 destination.
        if ip in ipaddress.ip_network("64:ff9b::/96") or ip in ipaddress.ip_network(
            "64:ff9b:1::/48"
        ):
            return False
        if ip.sixtofour or ip.teredo or "%" in str(ip):
            return False
    return True


def public_url(url):
    """Reject non-HTTP URLs, credentials, unusual ports and literal private IPs."""
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\\" in url
            or len(url) > 4096
            or parsed.port not in {None, 80, 443}
        ):
            raise ValueError()
        host = parsed.hostname
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # Names are checked by PublicResolver, including each redirect.
            if "%" in host or host.lower() in {"localhost", "localhost.localdomain"}:
                raise ValueError()
            host.encode("idna")
        else:
            if not is_public(address):
                raise ValueError()
    except (TypeError, ValueError, UnicodeError):
        raise HTTPException(400, "Only public HTTP(S) image URLs are allowed") from None
    return url


class PublicResolver(AbstractResolver):
    """Return only validated addresses to the actual connector, avoiding DNS races."""

    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM
        )
        if not records or any(not is_public(record[4][0]) for record in records):
            raise OSError("Non-public address refused")
        return [
            {
                "hostname": host,
                "host": address[0],
                "port": address[1],
                "family": address_family,
                "proto": protocol,
                "flags": socket.AI_NUMERICHOST,
            }
            for address_family, _, protocol, _, address in records
        ]

    async def close(self):
        pass


async def fetch_image(url):
    """Fetch within one deadline; validate redirects and limit streamed bytes."""
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    timeout = aiohttp.ClientTimeout(total=20, connect=5)
    try:
        async with asyncio.timeout(20):
            async with aiohttp.ClientSession(
                connector=connector, timeout=timeout
            ) as client:
                for _ in range(4):
                    public_url(url)
                    async with client.get(url, allow_redirects=False) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise HTTPException(
                                    502, "Image source redirect is incomplete"
                                )
                            url = urljoin(url, location)
                            continue
                        if response.status != 200:
                            raise HTTPException(502, "Image source is unavailable")
                        if (
                            response.content_length
                            and response.content_length > MAX_IMAGE_BYTES
                        ):
                            raise HTTPException(413, "Image exceeds server size limit")
                        content = bytearray()
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            if len(content) + len(chunk) > MAX_IMAGE_BYTES:
                                raise HTTPException(
                                    413, "Image exceeds server size limit"
                                )
                            content.extend(chunk)
                        return bytes(content)
                raise HTTPException(502, "Image source redirected too many times")
    except TimeoutError:
        raise HTTPException(504, "Image source timed out") from None
    except (aiohttp.ClientError, OSError):
        raise HTTPException(502, "Image source could not be reached safely") from None


def server_options(extras):
    """The HTTP server accepts processing options, never local model paths."""
    if not extras:
        return {}
    try:
        if not isinstance(extras, str) or len(extras) > 4096:
            raise ValueError()
        options = json.loads(extras)
        if not isinstance(options, dict) or not set(options) <= {
            "putalpha",
            "cc",
            "cloth_category",
            "sam_quant",
            "prompt",
        }:
            raise ValueError()
        if any(
            k in options and not isinstance(options[k], bool)
            for k in ("putalpha", "sam_quant")
        ):
            raise ValueError()
        if any(
            k in options and options[k] not in {0, 1, 2, 3}
            for k in ("cc", "cloth_category")
        ):
            raise ValueError()
        if "prompt" in options:
            if not isinstance(options["prompt"], list) or len(options["prompt"]) > 20:
                raise ValueError()
            for point in options["prompt"]:
                if not isinstance(point, dict) or set(point) != {
                    "type",
                    "data",
                    "label",
                }:
                    raise ValueError()
                if point["type"] != "point" or point["label"] not in {0, 1}:
                    raise ValueError()
                if not isinstance(point["data"], list) or len(point["data"]) != 2:
                    raise ValueError()
                if any(
                    not isinstance(n, (int, float)) or not 0 <= n <= 100000
                    for n in point["data"]
                ):
                    raise ValueError()
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(
            400, "Invalid or unsupported server processing options"
        ) from None
    return options


class RequestSizeLimit:
    """Bound the body before multipart parsing, including chunked requests."""

    def __init__(self, app, limit=MAX_REQUEST_BYTES, timeout=30):
        self.app, self.limit, self.timeout = app, limit, timeout

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()
        total = 0
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                message = await asyncio.wait_for(
                    receive(), timeout=max(0, deadline - time.monotonic())
                )
            except TimeoutError:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 408,
                        "headers": [
                            (b"content-type", b"text/plain"),
                            (b"connection", b"close"),
                        ],
                    }
                )
                await send(
                    {"type": "http.response.body", "body": b"Request body timed out"}
                )
                return
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > self.limit:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"text/plain"),
                            (b"connection", b"close"),
                        ],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"Request exceeds server size limit",
                    }
                )
                return
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
