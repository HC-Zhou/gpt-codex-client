"""Opt-in live protocol capture. Uses existing credentials; never invoked by pytest."""

# ruff: noqa: RUF001
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import time
from collections.abc import Iterator
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from gpt_codex_client import CodexClient, FunctionTool, Reasoning
from gpt_codex_client import _websocket as ws
from gpt_codex_client._config import load_token
from gpt_codex_client._converters import response_request_body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.5")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    token = load_token()
    if token is None or token.is_expired():
        raise SystemExit("An existing unexpired SDK token is required; login separately.")
    secrets = [token.access_token, token.refresh_token, token.id_token, token.account_id]
    start = time.monotonic()
    trace: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = []
    active_turn = 0

    def scrub(value: Any, key: str = "") -> Any:
        if isinstance(value, dict) and value.get("type") == "codex.rate_limits":
            return {k: v if k == "type" else "<redacted account quota>" for k, v in value.items()}
        if key.lower() == "x-codex-turn-state":
            return "<redacted opaque routing state>"
        if key.lower() in {
            "authorization",
            "chatgpt-account-id",
            "cookie",
            "set-cookie",
            "access_token",
            "refresh_token",
            "id_token",
        }:
            return "<redacted>"
        if key == "encrypted_content" and isinstance(value, str):
            if value.startswith("<redacted encrypted_content:"):
                return value
            digest = hashlib.sha256(value.encode()).hexdigest()
            return f"<redacted encrypted_content: chars={len(value)} sha256={digest}>"
        if isinstance(value, dict):
            return {k: scrub(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, str):
            for secret in secrets:
                if secret:
                    value = value.replace(secret, "<redacted>")
        return value

    def record(kind: str, **data: Any) -> None:
        item = scrub(
            {
                "seq": len(trace) + 1,
                "turn": active_turn,
                "elapsed_ms": round((time.monotonic() - start) * 1000, 3),
                "kind": kind,
                **data,
            }
        )
        trace.append(item)
        with (args.output / "trace.jsonl").open("a") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    def selected_headers(headers: Any) -> dict[str, str]:
        allowed = {
            "authorization",
            "chatgpt-account-id",
            "content-type",
            "accept",
            "user-agent",
            "originator",
            "openai-beta",
            "session-id",
            "x-client-request-id",
            "date",
            "server",
            "x-request-id",
            "content-encoding",
        }
        items = headers.raw_items() if hasattr(headers, "raw_items") else headers.items()
        return {k: v for k, v in items if k.lower() in allowed}

    class ObservedSocket:
        def __init__(self, socket: Any, connection: int) -> None:
            self.socket, self.connection = socket, connection

        def send(self, data: str) -> None:
            record(
                "ws.send",
                connection=self.connection,
                bytes=len(data.encode()),
                sha256=hashlib.sha256(data.encode()).hexdigest(),
                payload=json.loads(data),
            )
            self.socket.send(data)

        def recv(self, timeout: float | None = None) -> Any:
            frame = self.socket.recv(timeout=timeout)
            raw = frame.encode() if isinstance(frame, str) else frame
            record(
                "ws.recv",
                connection=self.connection,
                bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                payload=json.loads(frame),
            )
            return frame

        def close(self) -> None:
            record("ws.close", connection=self.connection)
            self.socket.close()

    original_connect = ws.connect_function
    connection_count = 0

    def traced_connect(url: str, **options: Any) -> ObservedSocket:
        nonlocal connection_count
        connection_count += 1
        record(
            "ws.connect",
            connection=connection_count,
            url=url,
            headers=selected_headers(options["additional_headers"]),
        )
        socket = original_connect(False)(url, **options)
        record(
            "ws.handshake",
            connection=connection_count,
            status=socket.response.status_code,
            headers=selected_headers(socket.response.headers),
        )
        return ObservedSocket(socket, connection_count)

    def request_hook(request: httpx.Request) -> None:
        # Records only this synthetic example's requests, never OAuth traffic.
        body = request.content
        record(
            "http.request",
            method=request.method,
            url=str(request.url),
            headers=selected_headers(request.headers),
            bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            payload=json.loads(body),
        )

    class ObservedBytes(httpx.SyncByteStream):
        def __init__(self, stream: httpx.SyncByteStream) -> None:
            self.stream = stream
            self.raw = bytearray()

        def __iter__(self) -> Iterator[bytes]:
            for chunk in self.stream:
                self.raw.extend(chunk)
                yield chunk

        def close(self) -> None:
            lines = []
            for line in self.raw.decode("utf-8", errors="replace").splitlines():
                if line.startswith("data:"):
                    with contextlib.suppress(ValueError):
                        line = "data: " + json.dumps(
                            scrub(json.loads(line[5:])), ensure_ascii=False
                        )
                lines.append(line)
            record(
                "http.response_body",
                bytes=len(self.raw),
                sha256=hashlib.sha256(self.raw).hexdigest(),
                sse_text="\n".join(lines),
            )
            self.stream.close()

    def response_hook(response: httpx.Response) -> None:
        record(
            "http.response_headers",
            status=response.status_code,
            headers=selected_headers(response.headers),
        )
        assert isinstance(response.stream, httpx.SyncByteStream)
        response.stream = ObservedBytes(response.stream)

    tool = FunctionTool(
        name="calculate_quote",
        description=(
            "Compute a demo quote from the supplied n"
            "umeric inputs. All prices are demonstrat"
            "ion data."
        ),
        parameters={
            "type": "object",
            "properties": {
                "unit_price": {"type": "number"},
                "quantity": {"type": "integer"},
                "discount_rate": {"type": "number"},
            },
            "required": ["unit_price", "quantity", "discount_rate"],
            "additionalProperties": False,
        },
        strict=True,
    )
    instructions = (
        "You are a quote assistant in a synthetic"
        " protocol demonstration. Use calculate_q"
        "uote exactly once when no tool result ex"
        "ists. After a tool result, answer briefl"
        "y in Chinese using that result; do not c"
        "all tools again unless asked to calculat"
        "e new numbers. Do not invent prices or c"
        "laim real purchases."
    )
    history: list[Any] = [
        {
            "role": "user",
            "content": (
                "演示报价：单价129.50元，数量2，折扣率10%。"
                "请调用calculate_quote计算折后总额，然后说明计算结果。"
            ),
        }
    ]
    session = "protocol-case-" + uuid4().hex
    opts: dict[str, Any] = dict(
        model=args.model,
        instructions=instructions,
        tools=[tool],
        tool_choice="auto",
        parallel_tool_calls=False,
        reasoning=Reasoning(effort="low"),
        preserve_context=True,
        session_id=session,
        prompt_cache_key=session,
    )
    manifest: dict[str, Any] = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "model_requested": args.model,
        "case": "synthetic quote, real model inference, local Decimal tool",
        "session_id": session,
        "redaction": (
            "credentials/account/quota/routing state "
            "redacted; encrypted_content replaced by "
            "length and SHA-256; wire bytes measured "
            "before redaction"
        ),
        "turns": turns,
        "status": "running",
    }
    ws.connect_function = lambda asynchronous: (
        original_connect(True) if asynchronous else traced_connect
    )
    try:
        with (
            httpx.Client(
                timeout=60, event_hooks={"request": [request_hook], "response": [response_hook]}
            ) as http,
            CodexClient(http_client=http, timeout=60, max_retries=0) as client,
        ):
            client._token = token
            for number, transport in [(1, "websocket"), (2, "websocket"), (3, "sse")]:
                active_turn = number
                if number == 3:
                    history.append(
                        {
                            "role": "user",
                            "content": "请根据已有工具结果，只输出折后总额，不重新调用工具。",
                        }
                    )
                body = response_request_body(input=history, stream=True, **opts)
                comparison = json.dumps({"type": "response.create", **body}).encode()
                record(
                    "sdk.full_request",
                    transport=transport,
                    payload=body,
                    websocket_full_equivalent_bytes=len(comparison),
                )
                before = time.monotonic()
                with client.responses.create(
                    input=history, transport=transport, stream=True, **opts
                ) as stream:
                    event_counts: dict[str, int] = {}
                    first_event_ms = None
                    for event in stream:
                        if first_event_ms is None:
                            first_event_ms = round((time.monotonic() - before) * 1000, 3)
                        event_counts[event.type] = event_counts.get(event.type, 0) + 1
                        record("sdk.event", event_type=event.type, payload=event.data)
                    result = stream.get_final_response()
                turns.append(
                    scrub(
                        {
                            "turn": number,
                            "transport": transport,
                            "response_id": result.id,
                            "model_returned": result.model,
                            "status": result.status,
                            "output_text": result.output_text,
                            "usage": asdict(result.usage) if result.usage else None,
                            "duration_ms": round((time.monotonic() - before) * 1000, 3),
                            "first_event_ms": first_event_ms,
                            "events": event_counts,
                        }
                    )
                )
                history.extend(result.to_input_items())
                if number == 1:
                    calls = [item for item in result.output if item.get("type") == "function_call"]
                    if len(calls) != 1 or calls[0].get("name") != "calculate_quote":
                        raise RuntimeError("Expected exactly one calculate_quote call")
                    call = calls[0]
                    values = json.loads(call["arguments"])
                    if values != {"unit_price": 129.5, "quantity": 2, "discount_rate": 0.1}:
                        raise RuntimeError("Tool arguments differ from the demonstration inputs")
                    total = (
                        Decimal(str(values["unit_price"]))
                        * values["quantity"]
                        * (1 - Decimal(str(values["discount_rate"])))
                    ).quantize(Decimal("0.01"))
                    output = json.dumps(
                        {
                            "currency": "CNY",
                            "subtotal": "259.00",
                            "discount_amount": "25.90",
                            "total": str(total),
                            "demo_data": True,
                        },
                        ensure_ascii=False,
                    )
                    item = {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": output,
                    }
                    history.append(item)
                    record("local.tool_result", payload=item)
            client.close_session(session)
            manifest["status"] = "completed"
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = scrub(
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "code": getattr(exc, "code", None),
                "status_code": getattr(exc, "status_code", None),
            }
        )
        record("run.error", **manifest["error"])
    finally:
        ws.connect_function = original_connect
        # SSE plaintext contains JSON strings, so redact opaque fields before publication too.
        for item in trace:
            if item["kind"] == "http.response_body":
                lines = []
                for line in item["sse_text"].splitlines():
                    if line.startswith("data:"):
                        with contextlib.suppress(ValueError):
                            line = "data: " + json.dumps(
                                scrub(json.loads(line[5:])), ensure_ascii=False
                            )
                    lines.append(line)
                item["sse_text"] = "\n".join(lines)
        (args.output / "trace.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in trace)
        )
        summary = []
        for turn in turns:
            rows = [item for item in trace if item["turn"] == turn["turn"]]
            full = next(item for item in rows if item["kind"] == "sdk.full_request")
            wire = next(item for item in rows if item["kind"] in {"ws.send", "http.request"})
            events = [item for item in rows if item["kind"] == "sdk.event"]
            received = [item for item in rows if item["kind"] == "ws.recv"]
            summary.append(
                {
                    "turn": turn["turn"],
                    "request_seq": wire["seq"],
                    "full_request_seq": full["seq"],
                    "terminal_seq": events[-1]["seq"],
                    "full_input_items": len(full["payload"]["input"]),
                    "sent_input_items": len(wire["payload"]["input"]),
                    "request_bytes": wire["bytes"],
                    "full_ws_equivalent_bytes": full["websocket_full_equivalent_bytes"],
                    "response_event_count": len(events),
                    "ws_received_json_bytes": sum(item["bytes"] for item in received)
                    if received
                    else None,
                }
            )
            for label, data in [("request", wire), ("response", events[-1])]:
                (args.output / f"turn-{turn['turn']}-{label}.json").write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n"
                )
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        manifest["trace_sha256"] = hashlib.sha256(
            (args.output / "trace.jsonl").read_bytes()
        ).hexdigest()
        manifest["source_files_sha256"] = {
            file.name: hashlib.sha256(file.read_bytes()).hexdigest()
            for file in sorted(Path("src/gpt_codex_client").glob("*.py"))
        }
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(scrub(manifest), ensure_ascii=False, indent=2))
    if manifest["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
