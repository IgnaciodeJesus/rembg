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

UI outputs use distinct temporary files instead of a shared output.png. Gradio
output caching and temporary-file retention still require operational review.
Resource-intensive model execution needs a separate process/concurrency policy
before multiuser deployment. Model checksum disabling remains an explicitly
trusted local setting; do not use it for externally supplied models.

Tests use synthetic addresses, mocked HTTP/DNS and an ASGI fixture; no model
weights, GPU or private images are loaded. Run:
`python -m unittest discover -s tests -p test_server_security.py -v`.
This is not full image/model regression or a production penetration test.

References: [OWASP2025](https://top10.owasp.org/2025/),
[aiohttp custom resolving](https://docs.aiohttp.org/en/stable/client_advanced.html#custom-resolving).
