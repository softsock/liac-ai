"""Local engineering inspector; transport contains no state mutation policy."""

import argparse
import asyncio
import codecs
import concurrent.futures
import sys
import threading
from contextlib import aclosing
from dataclasses import asdict
from pathlib import Path
from typing import AsyncIterator

import httpx

from vtuber.app import Config, list_models, open_runtime
from vtuber.contracts.events import RuntimeOutput, UserMessage, canonical_json
from vtuber.minds.lmstudio import LMStudioSettings, StreamProtocolError


async def input_lines() -> AsyncIterator[str]:
    """Keep stdin off the event loop without an executor that blocks Ctrl+C exit."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None | Exception] = asyncio.Queue(maxsize=16)
    stopped = threading.Event()

    def send(value: str | None | Exception) -> bool:
        if stopped.is_set():
            return False
        notification = queue.put(value)
        try:
            pending = asyncio.run_coroutine_threadsafe(notification, loop)
        except RuntimeError:
            notification.close()
            return False
        while not stopped.is_set():
            try:
                pending.result(timeout=0.1)
                return True
            except concurrent.futures.TimeoutError:
                continue
            except concurrent.futures.CancelledError:
                return False
        pending.cancel()
        return False

    def read_stdin() -> None:
        decoder = codecs.getincrementaldecoder(sys.stdin.encoding or "utf-8")()
        line = ""
        try:
            while not stopped.is_set():
                # Raw reads do not hold Python buffered-I/O locks during shutdown.
                data = sys.stdin.buffer.raw.read(1)
                if not data:
                    line += decoder.decode(b"", final=True)
                    if line:
                        send(line.rstrip("\r"))
                    send(None)
                    return
                text = decoder.decode(data)
                if text == "\n":
                    if not send(line.rstrip("\r")):
                        return
                    line = ""
                else:
                    line += text
        except Exception as error:
            send(error)

    # shortcut: daemonize a blocked console read; replace with a transport-native
    # reader if this process-only CLI becomes an embedded, restartable interface.
    reader = threading.Thread(target=read_stdin, name="vtuber-stdin", daemon=True)
    reader.start()
    try:
        while True:
            item = await queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        stopped.set()


class ConsoleOutput:
    def __init__(self) -> None:
        self.streaming = False

    def __call__(self, output: RuntimeOutput) -> None:
        if output.kind == "reply.started":
            print(f"\nFast {output.turn_id} r{output.revision}: ", end="", flush=True)
            self.streaming = True
        elif output.kind == "reply.delta":
            print(output.text, end="", flush=True)
        elif output.kind.startswith("reply."):
            detail = f": {output.text}" if output.kind == "reply.failed" else ""
            print(f"\n[{output.kind}{detail}]", flush=True)
            self.streaming = False
        else:
            if self.streaming:
                print()
            print(f"[{output.kind} r{output.revision}: {output.text}]", flush=True)


HELP = "Text sends a message. /state /events [count] /status /context /metrics /retry /help /quit"


async def run(config: Config) -> None:
    async with open_runtime(config, ConsoleOutput()) as runtime:
        print(f"Character Runtime | fast={config.fast_backend} | deep=fake | "
              f"character={config.character_id} | db={config.db}", flush=True)
        print(HELP, flush=True)
        async with aclosing(input_lines()) as lines:
            async for line in lines:
                user_text = line
                line = line.strip()
                if not line:
                    continue
                if line in ("/quit", "/exit"):
                    break
                if line == "/help":
                    print(HELP, flush=True)
                elif line == "/state":
                    print(canonical_json(asdict(runtime.journal.snapshot(config.character_id))), flush=True)
                elif line == "/status":
                    print(canonical_json({
                        "deep_cursor": runtime.journal.cursor(config.character_id),
                        "journal_sequence": runtime.journal.high_watermark(config.character_id),
                        "deep_error": runtime.deep_error,
                        "context_epoch": {"version": runtime.journal.context_epoch(config.character_id).version,
                            "cutoff": runtime.journal.context_epoch(config.character_id).compacted_through_sequence},
                        "fast": runtime.fast_diagnostics,
                        "last_cancellation_ms": runtime.last_cancellation_ms,
                    }), flush=True)
                elif line == "/context":
                    print(canonical_json(runtime.fast_diagnostics.get("context", {})), flush=True)
                elif line == "/metrics":
                    print(canonical_json({"generation": runtime.fast_diagnostics.get("generation"),
                        "preparation_ms": runtime.fast_diagnostics.get("preparation_ms"),
                        "last_cancellation_ms": runtime.last_cancellation_ms}), flush=True)
                elif line == "/retry":
                    runtime.retry_deep()
                    print("Deep notified", flush=True)
                elif line.split()[0] == "/events":
                    try:
                        parts = line.split()
                        count = int(parts[1]) if len(parts) == 2 else 10 if len(parts) == 1 else 0
                        if not 1 <= count <= 100:
                            raise ValueError
                    except ValueError:
                        print("Usage: /events [1..100]", flush=True)
                        continue
                    high = runtime.journal.high_watermark(config.character_id)
                    for event in runtime.journal.read(config.character_id, after=max(0, high - count)):
                        print(canonical_json({"sequence": event.sequence, "event_id": event.event_id,
                            "turn_id": event.turn_id, "kind": event.kind, "payload": event.payload}), flush=True)
                elif line.startswith("/"):
                    print(f"Unknown command. {HELP}", flush=True)
                else:
                    await runtime.submit(UserMessage(user_text, config.character_id))
    print("Runtime stopped; journal closed.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Character Runtime: fake or local Nemotron Fast; fake Deep")
    parser.add_argument("--db", type=Path, default=Config.db)
    parser.add_argument("--character", default="primary")
    parser.add_argument("--fast-delay", type=float, default=0.03, help="seconds per fake chunk")
    parser.add_argument("--deep-delay", type=float, default=2.0, help="seconds per fake batch")
    parser.add_argument("--deep-timeout", type=float, default=30.0)
    parser.add_argument("--fast-backend", choices=("fake", "lmstudio"), default="fake")
    parser.add_argument("--endpoint", default=LMStudioSettings.endpoint, help="LM Studio server origin")
    parser.add_argument("--model", default="", help="loaded instance ID from --list-models")
    parser.add_argument("--context-tokens", type=int, default=16384)
    parser.add_argument("--max-output-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--connect-timeout", type=float, default=2.0)
    parser.add_argument("--read-timeout", type=float, default=15.0, help="seconds without response data")
    parser.add_argument("--generation-timeout", type=float, default=45.0, help="total seconds including preflight")
    parser.add_argument("--identity", type=Path, help="UTF-8 Markdown; loaded at process start")
    parser.add_argument("--tokenizer", type=Path, default=Config.tokenizer, help="pinned local tokenizer.json")
    parser.add_argument("--list-models", action="store_true", help="inspect server models/loaded instances and exit")
    args = parser.parse_args()
    try:
        settings = LMStudioSettings(args.endpoint, args.model, args.max_output_tokens,
            args.temperature, args.top_p, args.connect_timeout, args.read_timeout, args.generation_timeout)
        if args.list_models:
            print(canonical_json(asyncio.run(list_models(settings))))
            return
        config = Config(args.db, args.character, args.fast_delay, args.deep_delay, args.deep_timeout,
                        args.fast_backend, settings, args.context_tokens, args.identity, args.tokenizer)
    except ValueError as error:
        parser.error(str(error))
    except (httpx.HTTPError, TimeoutError) as error:
        parser.exit(1, f"LM Studio connection failed ({type(error).__name__}); "
                    "check --endpoint, server status and LMSTUDIO_API_TOKEN.\n")
    try:
        asyncio.run(run(config))
    except KeyboardInterrupt:
        print("\nRuntime interrupted; resources closed.")
    except (OSError, ValueError, StreamProtocolError, httpx.HTTPError, TimeoutError) as error:
        parser.exit(1, f"Runtime setup failed ({type(error).__name__}): {error}\n")
