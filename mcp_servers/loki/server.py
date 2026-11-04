"""loki MCP server: log queries and error-pattern extraction.

Logs are application output = untrusted data. Everything returned is
redacted, capped and wrapped as untrusted before it can reach an LLM.

Run: python -m mcp_servers.loki.server  (stdio transport)
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import httpx
from mcp.server.fastmcp import FastMCP

from common.config import get_settings
from common.safety import TOOL_TIMEOUT_S, check_namespace, sanitize

mcp = FastMCP("loki")

ERROR_FILTER = "(?i)(error|exception|fatal|panic|failed|timeout|refused|denied)"

# normalization rules for grouping similar log lines into one pattern
_NORM_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\b[0-9a-f]{12,}\b", re.I), "<hexid>"),
    (re.compile(r'"[^"]*"'), "<str>"),
    (re.compile(r"\b\d+(\.\d+)?([eE][-+]?\d+)?\b"), "<num>"),
]


def normalize_log_pattern(line: str) -> str:
    """Reduce a log line to a stable pattern (numbers/ids/strings replaced)."""
    for pattern, replacement in _NORM_RULES:
        line = pattern.sub(replacement, line)
    return line.strip()[:200]


def _client() -> httpx.Client:
    return httpx.Client(base_url=get_settings().loki_url, timeout=TOOL_TIMEOUT_S)


def _parse_since(since: str) -> datetime:
    match = re.fullmatch(r"(\d+)([mhd])", since.strip())
    if not match:
        raise ValueError("since must look like 30m, 2h or 1d")
    value, unit = int(match.group(1)), match.group(2)
    delta = {"m": timedelta(minutes=value), "h": timedelta(hours=value),
             "d": timedelta(days=value)}[unit]
    return datetime.now(timezone.utc) - delta


def _query_range_logs(logql: str, since: str, limit: int) -> list[dict]:
    end = datetime.now(timezone.utc)
    with _client() as http:
        resp = http.get(
            "/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": int(_parse_since(since).timestamp() * 1e9),
                "end": int(end.timestamp() * 1e9),
                "limit": limit,
                "direction": "backward",
            },
        )
        resp.raise_for_status()
        body = resp.json()
    if body.get("status") != "success":
        raise ValueError(f"loki error: {body.get('message') or body}")
    return body["data"]["result"]


@mcp.tool()
def query_logs(logql: str, limit: int = 50, since: str = "30m",
               namespace: str | None = None) -> str:
    """Query raw logs from Loki with a LogQL selector expression.

    Args:
        logql: LogQL query, must start with a selector, e.g.
            {namespace="boutique", pod=~"checkoutservice.*"}
            optionally followed by |= or |~ line filters.
        limit: max lines to return (<= 200).
        since: time window like 30m, 2h, 1d.
    """
    ns = namespace or get_settings().app_namespace
    check_namespace(ns)
    q = logql.strip()
    if not q.startswith("{"):
        raise ValueError("LogQL must start with a '{' selector")
    if ";" in q or "\n" in q or len(q) > 400:
        raise ValueError("suspicious LogQL rejected")
    limit = max(1, min(limit, 200))
    streams = _query_range_logs(q, since, limit)
    lines = []
    for stream in streams:
        labels = ",".join(f"{k}={v}" for k, v in stream["stream"].items()
                          if k in ("namespace", "pod", "container"))
        lines.append(f"--- {{{labels}}}")
        for ts, text in stream["values"][-limit:]:
            lines.append(text)
    return sanitize("\n".join(lines) or "(no log lines matched)",
                    source="pod logs via Loki (UNTRUSTED)")


@mcp.tool()
def error_patterns(service: str, since: str = "30m", namespace: str | None = None,
                   top: int = 20) -> str:
    """Top recurring error patterns for a service, grouped by normalized
    template with counts and one example line each (log compression - keeps
    error summaries small enough for an LLM).

    Args:
        service: service name; matches pods named '<service>.*'.
    """
    ns = namespace or get_settings().app_namespace
    check_namespace(ns)
    if not service or not re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", service):
        raise ValueError("service must be a plain service name")
    top = max(1, min(top, 40))
    logql = (
        f'{{namespace="{ns}", pod=~"{service}.*"}} |~ "{ERROR_FILTER}"'
    )
    streams = _query_range_logs(logql, since, 500)
    counts: Counter[str] = Counter()
    example: dict[str, str] = {}
    total = 0
    for stream in streams:
        for _, text in stream["values"]:
            total += 1
            pattern = normalize_log_pattern(text)
            counts[pattern] += 1
            example.setdefault(pattern, text.strip()[:300])
    if not counts:
        return sanitize(f"(no error-like lines for {service} in the last {since})",
                        source="loki error patterns")
    out = [f"service={service} window={since} error_lines={total} distinct_patterns={len(counts)}"]
    for pattern, count in counts.most_common(top):
        out.append(f"\n[{count}x] {pattern}\n  example: {example[pattern]}")
    return sanitize("\n".join(out), source="loki error patterns (UNTRUSTED)")


if __name__ == "__main__":
    mcp.run()
