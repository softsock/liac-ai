"""Owned official OMP SDK lifecycle. Blocking SDK calls stay off the event loop."""
import asyncio
import json
import math
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from vtuber.contracts.deep import DeepUnavailable
from vtuber.contracts.trace import TraceSink, emit_trace, trace_enabled


def sdk_client(**kwargs):
    from omp_rpc import RpcClient
    return RpcClient(**kwargs)


def visible_session(messages):
    """Capture text context, excluding reasoning, signatures and provider internals."""
    result = []
    for message in messages:
        content = message.get('content', message.get('summary', ''))
        if isinstance(content, list):
            content = [({'type': 'text', 'text': block.get('text', '')} if block.get('type') == 'text'
                        else {'type': block.get('type', 'unknown'), 'omitted': True})
                       for block in content if isinstance(block, dict)]
        result.append({'role': message.get('role', 'unknown'), 'content': content})
    return result


@dataclass(frozen=True)
class OMPSettings:
    executable: str = 'omp'
    model: str = 'openai-codex/gpt-6-luna'
    data_dir: Path = Path('.data/luna')
    startup_timeout: float = 30.0
    request_timeout: float = 60.0

    def __post_init__(self) -> None:
        if not self.executable.strip() or not self.model.strip():
            raise ValueError('OMP executable and model must be nonempty')
        if any(not math.isfinite(t) or t <= 0 for t in (self.startup_timeout, self.request_timeout)):
            raise ValueError('OMP timeouts must be finite and positive')


class OMPTransport:
    def __init__(self, settings: OMPSettings, system_prompt: str, diagnostics: dict[str, object],
                 *, trace: TraceSink | None = None) -> None:
        self.settings = settings
        self.system_prompt = system_prompt
        self.diagnostics = diagnostics
        self.trace = trace
        self._lock = asyncio.Lock()
        self._client = None
        self._pending = None
        self._starting = False
        self._unsafe = False
        self._closed = False
        self._provider_blocked = False

    def _create(self):
        root = self.settings.data_dir.resolve()
        workspace = root / 'workspace'
        workspace.mkdir(parents=True, exist_ok=True)
        overlay = root / 'isolation.json'
        overlay.write_text(json.dumps({'mcp': {'enableProjectConfig': False}, 'disabledProviders': [
            'agent-plugins', 'agents', 'agents-md', 'claude', 'claude-md', 'claude-plugins',
            'cline', 'codex', 'cursor', 'custom-context', 'gemini', 'github', 'mcp-json',
            'native', 'omp-plugins', 'opencode', 'skillshare', 'ssh-json', 'vscode', 'windsurf']}), encoding='utf-8')
        env = dict(os.environ)
        env.update(OMP_PROFILE='', PI_PROFILE='', PI_NO_TITLE='1', PI_NO_PTY='1')
        return sdk_client(executable=self.settings.executable, model=self.settings.model,
            cwd=workspace, session_dir=root/'sessions', env=env, tools=(), no_skills=True,
            no_rules=True, no_ui=True, no_title=True, max_event_history=1024, max_stderr_chunks=16,
            startup_timeout=self.settings.startup_timeout, request_timeout=self.settings.request_timeout,
            extra_args=('--no-extensions', '--no-lsp', '--config', str(overlay),
                        '--system-prompt', self.system_prompt))

    async def _call(self, function, *args, **kwargs):
        self._pending = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        await asyncio.wait((self._pending,))
        return self._pending.result()

    async def _dispose(self):
        client = self._client
        try:
            # Startup may still create a child: join it before attempting stop.
            if self._starting and self._pending:
                with suppress(Exception):
                    await asyncio.wait_for(asyncio.shield(self._pending), self.settings.startup_timeout + 2)
                if not self._pending.done():
                    raise RuntimeError('OMP startup did not finish')
            if client is not None:
                if not self._starting:
                    with suppress(Exception):
                        await asyncio.wait_for(asyncio.to_thread(client.abort), 3)
                confirmed = await asyncio.wait_for(asyncio.to_thread(client.stop), 15)
                if confirmed is not True:
                    raise RuntimeError('OMP teardown unconfirmed')
            if self._pending:
                with suppress(Exception):
                    await asyncio.wait_for(asyncio.shield(self._pending), 2)
                if not self._pending.done():
                    raise RuntimeError('OMP operation did not exit')
            self._client = None
            self.diagnostics['lifecycle'] = 'stopped'
        except Exception:
            self._unsafe = True
            self.diagnostics['lifecycle'] = 'unsafe'
        finally:
            self._starting = False
            self.diagnostics['cleanup_confirmed'] = not self._unsafe

    async def _cleanup(self):
        cleanup = asyncio.create_task(self._dispose())
        cancelled = False
        # Repeated cancellation must not release the lifecycle lock early.
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        await cleanup
        if cancelled:
            raise asyncio.CancelledError

    async def request(self, prompt: str, *, request_id: str = '') -> str:
        if len(prompt.encode('utf-8')) > 524288:
            raise ValueError('OMP request exceeds 512 KiB; evidence was not truncated')
        async with self._lock:
            if self._provider_blocked:
                raise DeepUnavailable('usage_limit_reached; restart after provider availability returns')
            if self._unsafe or self._closed:
                raise RuntimeError('OMP transport is unavailable or unsafe')
            start = perf_counter()
            try:
                if self._client is None:
                    self.diagnostics['lifecycle'] = 'starting'
                    # Construction does not start a process; import and disk I/O stay off-loop.
                    create = asyncio.create_task(asyncio.to_thread(self._create))
                    try:
                        await asyncio.wait((create,))
                        self._client = create.result()
                    except asyncio.CancelledError:
                        with suppress(Exception):
                            while not create.done():
                                with suppress(asyncio.CancelledError):
                                    await asyncio.wait((create,))
                            self._client = create.result()
                        raise
                    self._starting = True
                    await self._call(self._client.start)
                    self._starting = False
                    state = await self._call(self._client.get_state)
                    actual = state.model.provider+'/'+state.model.id if state.model else None
                    if actual != self.settings.model:
                        raise ValueError('OMP selected a different model')
                    self.diagnostics.update(session_id=state.session_id, model=actual)
                self.diagnostics['lifecycle'] = 'analyzing'
                if trace_enabled(self.trace):
                    history = None
                    history_error = None
                    try:
                        # The pinned SDK getter paginates without a total deadline.
                        # Its command boundary supports one bounded local RPC instead.
                        payload = await self._call(self._client._command, 'get_messages', {}, timeout=.1)
                        history = visible_session(payload['messages'])
                    except Exception as error:
                        history_error = type(error).__name__
                    emit_trace(self.trace, 'omp.context', request_id,
                               system_prompt=self.system_prompt, session_messages=history,
                               history_error=history_error, current_prompt=prompt,
                               session_id=self.diagnostics.get('session_id'), model=self.settings.model,
                               scope='OMP session view, not the provider HTTP request')
                turn = await self._call(self._client.prompt_and_wait, prompt, timeout=self.settings.request_timeout)
                if turn.assistant_message and 'usage_limit_reached' in str(turn.assistant_message.get('errorMessage', '')):
                    self._provider_blocked = True
                    self.diagnostics['provider_status'] = 'usage_limit_reached'
                    raise DeepUnavailable('usage_limit_reached')
                if (turn.result is None or turn.result.status != 'completed' or not turn.result.session_settled
                        or turn.assistant_message is None or turn.assistant_message.get('stopReason') != 'stop'):
                    raise ValueError('OMP prompt did not complete with settled assistant text')
                text = turn.require_assistant_text()
                if len(text.encode('utf-8')) > 65536:
                    raise ValueError('OMP assistant response exceeds 64 KiB')
                self.diagnostics.update(lifecycle='ready', usage=turn.assistant_message.get('usage', {}), error=None)
                emit_trace(self.trace, 'omp.completed', request_id, usage=turn.assistant_message.get('usage', {}),
                           session_id=self.diagnostics.get('session_id'))
                return text
            except BaseException as error:
                self.diagnostics['error'] = type(error).__name__
                await self._cleanup()
                raise
            finally:
                self.diagnostics['duration_ms'] = round((perf_counter()-start)*1000, 3)

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            await self._cleanup()
