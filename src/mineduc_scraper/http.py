"""Polite HTTP client: fixed rate limit, retries with backoff, optional disk cache."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "mineduc-curriculum-db/1.0 (open dataset builder; "
    "+https://github.com/mineduc-curriculum-db)"
)
DEFAULT_DELAY = 1.5
DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 4


class PoliteClient:
    """Sequential, rate-limited HTTP client.

    A single client instance guarantees at least ``delay`` seconds between the
    *start* of consecutive requests, so the crawl stays within the polite
    budget stated in SPEC.md regardless of how callers interleave fetches.
    """

    def __init__(
        self,
        delay: float = DEFAULT_DELAY,
        cache_dir: Optional[Path] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.delay = delay
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "es-CL,es;q=0.9",
            },
            timeout=timeout,
            follow_redirects=True,
        )
        self._last_request = 0.0
        self.stats = {"network": 0, "cache": 0, "errors": 0}

    # -- context manager ---------------------------------------------------
    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- internals ---------------------------------------------------------
    def _cache_path(self, url: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{digest}.html"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    # -- public API --------------------------------------------------------
    def get_text(self, url: str, accept: str = "text/html") -> str:
        """Fetch ``url`` as text, using the disk cache when available."""
        cache_path = self._cache_path(url)
        if cache_path and cache_path.exists():
            self.stats["cache"] += 1
            return cache_path.read_text(encoding="utf-8")

        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            try:
                response = self._client.get(url, headers={"Accept": accept})
                if response.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"retryable status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001 - retry any transport/status error
                last_error = exc
                backoff = self.delay * (2 ** attempt)
                log.warning(
                    "fetch failed (%s/%s) %s: %s - retrying in %.1fs",
                    attempt, MAX_RETRIES, url, exc, backoff,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(backoff)
                continue

            self.stats["network"] += 1
            text = response.text
            if cache_path:
                cache_path.write_text(text, encoding="utf-8")
            return text

        self.stats["errors"] += 1
        raise RuntimeError(f"giving up on {url}: {last_error}")

    def get_json(self, url: str):
        import json

        return json.loads(self.get_text(url, accept="application/vnd.api+json"))

    def download(self, url: str, destination: Path) -> Path:
        """Fetch a binary file to ``destination``, skipping it if already present.

        Used for the Programa de Estudio PDFs, which are large (2-6 MB each)
        and are what makes the indicator pass worth caching between runs.
        """
        destination = Path(destination)
        if destination.exists() and destination.stat().st_size > 0:
            self.stats["cache"] += 1
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)

        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            try:
                partial = destination.with_suffix(destination.suffix + ".part")
                with self._client.stream("GET", url) as response:
                    response.raise_for_status()
                    with partial.open("wb") as handle:
                        for chunk in response.iter_bytes(65536):
                            handle.write(chunk)
                partial.replace(destination)
            except Exception as exc:  # noqa: BLE001 - retry any transport error
                last_error = exc
                backoff = self.delay * (2 ** attempt)
                log.warning("download failed (%s/%s) %s: %s - retrying in %.1fs",
                            attempt, MAX_RETRIES, url, exc, backoff)
                if attempt < MAX_RETRIES:
                    time.sleep(backoff)
                continue
            self.stats["network"] += 1
            return destination

        self.stats["errors"] += 1
        raise RuntimeError(f"giving up downloading {url}: {last_error}")
