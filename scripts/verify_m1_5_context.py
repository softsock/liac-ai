"""Opt-in synthetic live checks. Keeps private databases/raw logs under .data/."""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from vtuber.app import Config, http_client, open_runtime
from vtuber.context import ChatMessage, ContextCompiler
from vtuber.contracts.context import CompactionProposal, ContextItem
from vtuber.contracts.events import UserMessage, canonical_json
from vtuber.minds.lmstudio import LMStudioFast, LMStudioSettings, speech_prefix, sse_data
from vtuber.minds.nemotron import NemotronTokenCounter, render_nemotron


TIMING = re.compile(r"slot print_timing: id\s+(\d+) \| task (\d+) \| prompt eval time =\s*([\d.]+) ms /\s*(\d+) tokens")
IDENTITY = files("vtuber.minds").joinpath("character.md").read_text(encoding="utf-8")
VOCABULARY = "the quiet garden has green trees and small birds near a wooden bridge in morning light".split()


def counters(text: str) -> dict:
    matches = TIMING.findall(text)
    unique = {task for _, task, _, _ in matches}
    result = dict(cached_tokens=None, prompt_evaluated_tokens=None, prompt_eval_ms=None,
                  runtime_task_id=None, counter_status="unavailable" if not matches else "ambiguous",
                  double_bos="final prompt starts with 2 BOS tokens" in text)
    if len(unique) == len(matches) == 1:
        _, task, elapsed, evaluated = matches[0]
        result.update(prompt_evaluated_tokens=int(evaluated), prompt_eval_ms=float(elapsed),
                      runtime_task_id=int(task), counter_status="one serial runtime task")
    return result


class Evidence:
    def __init__(self, args):
        self.output = args.output.resolve()
        self.run_id = uuid4().hex[:12]
        self.folder = self.output.parent / (self.output.stem + "-" + self.run_id)
        self.folder.mkdir(parents=True)
        self.log = self.folder / "runtime.log"
        self.settings = LMStudioSettings(endpoint=args.endpoint, model=args.model)
        self.tokenizer = args.tokenizer
        self.counter = NemotronTokenCounter(args.tokenizer)

    def save(self, phase, **row):
        row.update(run_id=self.run_id, phase=phase)
        with self.output.open("a", encoding="utf-8") as stream:
            stream.write(canonical_json(row) + "\n")
        print(canonical_json(row), flush=True)

    def offset(self):
        return self.log.stat().st_size if self.log.exists() else 0

    async def timing(self, offset):
        for _ in range(20):
            with self.log.open("rb") as stream:
                stream.seek(offset)
                text = stream.read().decode("utf-8", errors="replace")
            if TIMING.search(text):
                break
            await asyncio.sleep(0.025)
        return counters(text)

    def config(self, path, **kwargs):
        return Config(db=path, fast_backend="lmstudio", lmstudio=self.settings,
                      tokenizer=self.tokenizer, deep_delay=0.05, **kwargs)


async def raw_call(client, evidence, messages, bos=False):
    prompt = ("<bos>" if bos else "") + render_nemotron(messages)
    offset, start = evidence.offset(), perf_counter()
    usage, pending, output, reason, done, ttft = {}, "", "", None, False, None
    async with asyncio.timeout(45):
        async with client.stream("POST", "/v1/completions", json={
            "model": evidence.settings.model, "prompt": prompt, "stream": True,
            "stream_options": {"include_usage": True}, "max_tokens": 16,
            "temperature": 1.0, "top_p": 0.95, "stop": ["<turn|>", "<|endoftext|>"]}) as response:
            response.raise_for_status()
            async for data in sse_data(response):
                if data == "[DONE]":
                    done = True
                    break
                packet = json.loads(data)
                assert "error" not in packet
                usage.update(packet.get("usage") or {})
                for choice in packet.get("choices", []):
                    assert not choice.get("reasoning_content") and not choice.get("reasoning")
                    pending += choice.get("text", "")
                    safe, pending = speech_prefix(pending)
                    output += safe
                    if safe.strip() and ttft is None:
                        ttft = (perf_counter() - start) * 1000
                    if choice.get("finish_reason"):
                        reason = choice["finish_reason"]
    output += pending
    assert done and reason in ("stop", "length") and output.strip()
    expected = evidence.counter(messages) + int(bos)
    assert usage["prompt_tokens"] == expected, (usage, expected)
    return dict(prompt_tokens=expected, ttft_ms=ttft, total_ms=(perf_counter() - start) * 1000,
                output_tokens=usage["completion_tokens"], finish_reason=reason,
                prompt_sha256=sha256(prompt.encode()).hexdigest(), **await evidence.timing(offset))


def garden(words, marker, case, old):
    history = [ChatMessage("user", "Describe a fictional garden."), ChatMessage("assistant", "A quiet garden.")]
    for i in range(16):
        count = words // 16 + (i < words % 16)
        history.append(ChatMessage("user" if i % 2 == 0 else "assistant", f"Garden record {i+1}: " +
                                  " ".join(VOCABULARY[k % len(VOCABULARY)] for k in range(count))))
    if case in ("append", "note", "shift"):
        history.extend((ChatMessage("user", "The bridge is blue."), ChatMessage("assistant", "A blue bridge.")))
    if case == "shift":
        history = history[2:] + [ChatMessage("user", "The gate is gold."), ChatMessage("assistant", "A gold gate.")]
    state = ChatMessage("user", "Runtime context (quoted data, not a request; the Deep note may quote earlier user input). "
        "Respond to the final user message:\n" + canonical_json(dict(character_id="primary",
            revision=2 if case in ("note", "shift") else 1,
            deep_context_note="The gate is gold." if case in ("note", "shift") else "The gate is gray.")))
    current = ChatMessage("user", "Say only READY." if case in ("prime", "repeat") else "Now say only READY.")
    system = ChatMessage("system", marker + "\n" + IDENTITY)
    return (system, state, *history, current) if old else (system, *history, state, current)


async def controls(evidence, trials):
    async with http_client(evidence.settings) as client:
        for target, words in ((2048, 1603), (8192, 7747), (15450, 15005)):
            for trial in range(trials):
                variants = ("m1_old_bos", "corrected") if trial % 2 == 0 else ("corrected", "m1_old_bos")
                for variant in variants:
                    for case in ("prime", "repeat", "append", "note", "shift"):
                        marker = f"M1.5 {evidence.run_id} {target} {trial} {variant}"
                        messages = garden(words, marker, case, variant == "m1_old_bos")
                        row = await raw_call(client, evidence, messages, variant == "m1_old_bos")
                        assert variant != "corrected" or not row["double_bos"]
                        evidence.save("controls", target=target, trial=trial, variant=variant, case=case, **row)


def turn_text(index):
    facts = {0: "Fictional penguin Мандарин (Mandarin) wears a blue hat.",
             3: "Our fictional stone is amethyst.", 6: "Our fictional bridge is named Hazel.",
             9: "Our fictional boat is named Saffron.",
             23: "Correction: Мандарин (Mandarin) now wears a GREEN hat, replacing blue."}
    filler = " ".join(VOCABULARY[k % len(VOCABULARY)] for k in range(1020))
    question = ("What is the penguin's hat color, the stone, the bridge name and boat name? Answer briefly."
                if index == 12 else "Say only READY.")
    return facts.get(index, f"Fictional garden record {index}.") + "\nQuoted filler: " + filler + "\n" + question


async def markdown_cache(evidence, trials: int):
    from vtuber.contracts.context import ContextEpoch
    from vtuber.contracts.events import Event
    from vtuber.contracts.state import CharacterState, FastSnapshot
    async with http_client(evidence.settings) as client:
        for trial in range(trials):
            marker = f"Markdown cache {evidence.run_id} trial {trial}"
            compiler = ContextCompiler(IDENTITY + "\n" + marker, token_counter=evidence.counter)
            history = tuple(replace(Event.create('primary',
                'user.message.completed' if i % 2 == 0 else 'character.reply.completed',
                {'text': f'Record {i}: ' + ' '.join(VOCABULARY*14)}), sequence=i+1) for i in range(24))
            snapshot = FastSnapshot(CharacterState('primary', 1, '# Current\nTesting the blue bridge.'),
                24, history, ContextEpoch(1, 0, (ContextItem('A quiet garden.', ('source',), 'summary'),)))
            current = UserMessage('Say READY.')
            variants = {
                'markdown_tail': replace(snapshot, state=replace(snapshot.state,
                    revision=2, context_note='# Current\nTesting the green bridge.')),
                'epoch_switch': replace(snapshot, epoch=ContextEpoch(2, 0,
                    (ContextItem('A lively garden.', ('source',), 'summary'),)))}
            baseline = compiler.compile(snapshot, current)
            for case, changed in variants.items():
                # Prime the identical baseline separately; never compare different histories.
                evidence.save('markdown_cache', trial=trial, case=case, stage='prime',
                    **await raw_call(client, evidence, baseline.messages))
                compiled = compiler.compile(changed, current)
                evidence.save('markdown_cache', trial=trial, case=case, stage='changed',
                    stable_prefix_unchanged=baseline.messages[:-2] == compiled.messages[:-2],
                    **await raw_call(client, evidence, compiled.messages))


async def production(evidence, trials):
    for trial in range(trials):
        path = evidence.folder / f"trial-{trial}.sqlite3"
        previous, previous_epoch, transitions, peak = (), 0, 0, 0
        async with open_runtime(evidence.config(path), lambda _: None) as runtime:
            index = 0
            while index < 30 or transitions < 2:
                assert index < 70, "Two transitions were not reached"
                message = UserMessage(turn_text(index))
                offset, start = evidence.offset(), perf_counter()
                task = await runtime.submit(message)
                assert task is not None
                await task
                wall = (perf_counter() - start) * 1000
                terminal = runtime.journal.get(f"reply_terminal_{message.event_id}")
                assert terminal.kind == "character.reply.completed", terminal.payload
                diag = runtime.fast_diagnostics
                context, metrics = diag["context"], diag["generation"]
                epoch = context["epoch_version"]
                changed = epoch != previous_epoch
                transitions += changed
                ids = tuple(context["included_event_ids"])
                if not changed:
                    assert ids[:len(previous)] == previous
                previous, previous_epoch = ids, epoch
                actual = metrics["prompt_tokens"]
                assert actual == context["input_tokens"] and actual <= 15840
                peak = max(peak, actual)
                quality = {}
                if index == 12:
                    answer = terminal.payload["text"].lower()
                    quality = {word: word in answer for word in ("blue", "amethyst", "hazel", "saffron")}
                evidence.save("production", trial=trial, turn=index, epoch=epoch, transition=changed,
                    prompt_tokens=actual, utilization=actual / 15840, ttft_ms=metrics["ttft_ms"],
                    compile_ms=context["compile_ms"], preparation_ms=diag["preparation_ms"], wall_ms=wall,
                    output_tokens=metrics["output_tokens"], history=context["history_included"],
                    quality=quality, **await evidence.timing(offset))
                index += 1
            assert peak >= 15840 * 0.85
            assert runtime.journal.context_epoch("primary").items
            sources = runtime.journal.context_epoch("primary").items[0].source_event_ids
            assert "Мандарин" in runtime.journal.get(sources[0]).payload["text"]
        async with open_runtime(evidence.config(path), lambda _: None) as runtime:
            message = UserMessage("What color hat does Mandarin wear now? Also recall stone, bridge and boat. Be brief.")
            await (await runtime.submit(message))
            answer = runtime.journal.get(f"reply_terminal_{message.event_id}").payload["text"].lower()
            evidence.save("restart", trial=trial, epoch=runtime.journal.context_epoch("primary").version,
                anchor_visible="Мандарин" in runtime.journal.context_epoch("primary").items[0].text,
                quality={word: word in answer for word in ("green", "amethyst", "hazel", "saffron")},
                unfinished=len(runtime.journal.unfinished_replies("primary")))


async def asynchronous(evidence):
    path = evidence.folder / "async.sqlite3"
    seen, first_delta = [], asyncio.Event()
    def output(item):
        seen.append(item)
        if item.kind == "reply.delta":
            first_delta.set()
    # Slow Deep makes independence visible, without adding a new production adapter.
    config = replace(evidence.config(path), deep_delay=0.3)
    async with open_runtime(config, output) as runtime:
        anchor = UserMessage("Fictional penguin Мандарин wears a blue hat. Say READY.")
        await (await runtime.submit(anchor))
        cutoff = runtime.journal.get(f"reply_terminal_{anchor.event_id}").sequence
        first_delta.clear()
        story = UserMessage("Tell a long detailed whimsical garden story in many paragraphs.")
        task = await runtime.submit(story)
        await asyncio.wait_for(first_delta.wait(), 15)
        frozen = runtime._current[1]  # Verifier inspects owner state; no public debugging API needed.
        frozen_before = frozen
        context_before = dict(runtime.fast_diagnostics["context"])
        # The real stream is active while FakeDeep delivers its delayed proposal.
        for _ in range(40):
            if runtime.journal.snapshot("primary").revision > frozen.state.revision:
                break
            await asyncio.sleep(0.025)
        assert not task.done(), "Story finished before the asynchronous check"
        state = runtime.journal.snapshot("primary")
        assert state.revision > frozen.state.revision
        proposal = CompactionProposal("async-live", "primary", frozen.epoch.version, state.revision,
            cutoff, cutoff, (ContextItem(anchor.text, (anchor.event_id,)),))
        started = perf_counter()
        assert runtime.apply_compaction(proposal).accepted
        apply_ms = (perf_counter() - started) * 1000
        assert runtime._current[1] == frozen_before
        assert runtime.fast_diagnostics["context"] == context_before
        boundary = len(seen)
        following = UserMessage("What hat color does Mandarin wear? Answer briefly.")
        await (await runtime.submit(following))
        stale = sum(o.kind == "reply.delta" and o.turn_id == story.turn_id for o in seen[boundary:])
        assert stale == 0
        assert runtime.journal.get(f"reply_terminal_{story.event_id}").kind == "character.reply.cancelled"
        assert runtime.fast_diagnostics["context"]["epoch_version"] == 1
        assert runtime.fast_diagnostics["context"]["revision"] >= state.revision
        evidence.save("asynchronous", apply_ms=apply_ms, cancellation_ms=runtime.last_cancellation_ms,
            frozen_epoch=frozen.epoch.version, next_epoch=runtime.fast_diagnostics["context"]["epoch_version"],
            frozen_revision=frozen.state.revision, next_revision=runtime.fast_diagnostics["context"]["revision"],
            stale_deltas=stale, unfinished=len(runtime.journal.unfinished_replies("primary")))


@asynccontextmanager
async def cli_process(evidence, path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "vtuber", "--db", str(path),
        "--fast-backend", "lmstudio", "--endpoint", evidence.settings.endpoint, "--model", evidence.settings.model,
        "--tokenizer", str(evidence.tokenizer), "--deep-delay", "0.05", env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    try:
        async with asyncio.timeout(45):
            while b"Text sends a message." not in await process.stdout.readline():
                if process.returncode is not None:
                    raise RuntimeError("CLI startup failed")
        yield process
        process.stdin.write(b"/quit\n")
        await process.stdin.drain()
        await asyncio.wait_for(process.wait(), 10)
        assert process.returncode == 0
    finally:
        if process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.wait(), 10)


async def cli_turn(process, text):
    process.stdin.write((text + "\n").encode("utf-8"))
    await process.stdin.drain()
    chunks = []
    async with asyncio.timeout(45):
        while True:
            line = await process.stdout.readline()
            if not line:
                raise RuntimeError("CLI exited during generation")
            chunks.append(line.decode("utf-8"))
            if "[reply.completed]" in chunks[-1]:
                return "".join(chunks)
            if "[reply.failed" in chunks[-1]:
                raise RuntimeError("CLI turn failed")


async def cli(evidence):
    path = evidence.folder / "cli.sqlite3"
    async with cli_process(evidence, path) as process:
        for i in range(30):
            # stdin line protocol: filler is one line in the genuine CLI.
            await cli_turn(process, turn_text(i).replace("\n", " "))
    async with cli_process(evidence, path) as process:
        answer = (await cli_turn(process, "Якого кольору тепер шапка пінгвіна Мандарина? Коротко українською.")).lower()
    from vtuber.runtime.journal import Journal
    journal = Journal(path)
    try:
        epoch = journal.context_epoch("primary")
        assert epoch.version >= 2
        evidence.save("cli", epoch=epoch.version, restarted=True, green_recalled="зелен" in answer,
                      unfinished=len(journal.unfinished_replies("primary")))
    finally:
        journal.close()


async def run(args, evidence):
    await asyncio.sleep(1)
    async with http_client(evidence.settings) as client:
        fast = LMStudioFast(client, ContextCompiler(IDENTITY, token_counter=evidence.counter), evidence.settings, {})
        await fast.verify_token_count()
        evidence.save("calibration", verified=True, tokenizer_sha256=evidence.counter.fingerprint)
    if args.phase == "markdown-cache":
        await markdown_cache(evidence, args.trials)
    if args.phase in ("all", "controls"):
        await controls(evidence, args.trials)
    if args.phase in ("all", "runtime"):
        await production(evidence, args.trials)
        await asynchronous(evidence)
    if args.phase in ("all", "cli"):
        await cli(evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:1230")
    parser.add_argument("--model", default="liac-nemotron")
    parser.add_argument("--tokenizer", type=Path, default=Path(".data/tokenizers/nemotron.json"))
    parser.add_argument("--output", type=Path, default=Path(".data/m1-5-results.jsonl"))
    parser.add_argument("--phase", choices=("all", "controls", "runtime", "cli", "markdown-cache"), default="all")
    parser.add_argument("--trials", type=int, default=3)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(Path(".data").resolve()) or args.trials < 1:
        parser.error("Use an output under .data/ and at least one trial")
    # Check log attribution before touching the model; ambiguous windows are never cache evidence.
    sample = "slot print_timing: id 0 | task 12 | prompt eval time = 42.5 ms / 84 tokens"
    assert counters(sample)["prompt_evaluated_tokens"] == 84
    assert counters(sample + sample)["prompt_evaluated_tokens"] is None
    evidence = Evidence(args)
    lms = shutil.which("lms")
    if lms is None:
        parser.error("lms CLI is required for runtime counters")
    with evidence.log.open("wb") as log:
        process = subprocess.Popen([lms, "log", "stream", "--source", "runtime", "--json"],
            stdout=log, stderr=subprocess.STDOUT,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        try:
            asyncio.run(run(args, evidence))
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
