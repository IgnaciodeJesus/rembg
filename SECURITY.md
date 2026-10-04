# Security of this local fork

The optional HTTP server defaults to loopback. Docker also publishes only on
loopback by default. Explicit LAN/public binding needs an authenticated reverse
proxy, TLS, rate/concurrency limits and an access policy; this server does not
claim to provide application authentication itself. Do not expose it directly.

The URL API permits public HTTP(S) on ports80/443, rejects credentials and private
addresses, validates every redirect, and pins the connector to public DNS answers.
Fetches have a20-second total deadline and10MiB decoded response limit. Requests
are limited to12MiB and a30-second body deadline before multipart parsing,
including chunked bodies. HTTP model
names match exactly; local custom model paths/providers are unavailable in the
HTTP/UI extras. Local CLI custom models remain available to a trusted caller.

API and UI share one non-blocking inference slot and retain only one model
session. A concurrent API call receives503/Retry-After, not an unbounded model
queue. Access logging is disabled so source URLs and query values are not
written to access logs. Uvicorn admits at most16 concurrent connections/tasks; Gradio queues at
most4 jobs with concurrency1. Images are verified/decoded before model loading,
limited to20 million pixels and one frame; erosion size is capped at255.
Model failures return a generic503 and discard the cached session for a later
retry. This does not establish a killable inference deadline or an OS memory
limit: those remain necessary before an exposed multiuser service.

The UI uses a file upload so Gradio does not decode an unchecked image during
input preprocessing. Raw FileData across all input components is validated
before Gradio's cache mover: only regular files registered by this interface's
bounded upload endpoint and contained in its upload cache are accepted. Remote
URLs, foreign local paths and symlinks are rejected before download/copy or
model construction. Component validators alone are too late for this boundary.
Output is an image owned by Gradio's cache, without a second
untracked temporary file. Cache cleanup runs every60 seconds for files older
than one hour, and manual flagging is disabled. This bounds retention time, not
disk consumption under arbitrary sustained traffic; an authenticated proxy,
rate policy and disk/process quotas are still required for multiuser deployment.
Model checksum disabling remains an explicitly trusted local setting; do not use
it for externally supplied models.

Tests use synthetic addresses, mocked HTTP/DNS and an ASGI fixture. The CPU smoke
test uses ONNX Runtime's bundled sigmoid example and the real rembg processing
pipeline; it never downloads segmentation weights, uses a GPU or opens private
images. Run:
`python -m unittest discover -s tests -p test_server_security.py -v`.
This is not full image/model regression or a production penetration test.

With the CPU/CLI extras installed in an isolated environment, run
`python -m unittest discover -s tests -p 'test_server_*.py' -v` for the real
FastAPI/Gradio/Pillow integration with synthetic images and mocked model calls.
It exercises upload, queue, managed output cleanup, API/UI contention, malformed
images/options and failed-model recovery. The additional smoke test executes a real CPU ONNX graph, but does not validate
background-removal accuracy, downloaded model weights or GPU support, and does
not start an exposed service. The optional server is not
installed in Hermes; changes to this fork do not activate a Mortymer service.

References: [OWASP2025](https://top10.owasp.org/2025/),
[aiohttp custom resolving](https://docs.aiohttp.org/en/stable/client_advanced.html#custom-resolving).
[Gradio cache/queue controls](https://www.gradio.app/docs/gradio/blocks),
[Pillow image limits](https://pillow.readthedocs.io/en/stable/reference/Image.html).

The server extras now require patched Gradio6.29.1, FastAPI0.142.2,
Starlette1.7.0 and python-multipart0.0.32 or later compatible versions. A fresh
isolated CPU/CLI installation from official PyPI passed `pip check`, the15
server tests and a query of84 package/version pairs with no known OSV advisories
on2026-10-04 UTC. This is a dated dependency check, not assurance against future
advisories. Existing installations must reinstall the updated extras; no shared
Hermes environment was modified. The requirements avoid resolver constraints
that previously selected vulnerable multipart/Starlette versions.
