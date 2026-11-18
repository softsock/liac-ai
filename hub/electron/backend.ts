import { execFile, spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { TextDecoder } from 'node:util';
import type { Inspection, ProcessStatus } from '../contract';

const FRAME_LIMIT = 1024 * 1024;
const REQUEST_TIMEOUT = 5_000;

type Reply = { resolve: (value: unknown) => void; reject: (error: Error) => void };
type Connection = {
  child: ChildProcessWithoutNullStreams;
  closed: Promise<void>;
  ready: Reply;
  pending: Map<number, Reply>;
  terminating?: Promise<void>;
};

function deadline<T>(promise: Promise<T>, ms: number, code: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  return Promise.race([
    promise,
    new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error(code)), ms);
    }),
  ]).finally(() => clearTimeout(timer));
}

function terminate(connection: Connection): Promise<void> {
  const { child } = connection;
  return connection.terminating ??= (async () => {
    if (child.pid !== undefined && child.exitCode === null && child.signalCode === null) {
      if (process.platform === 'win32') {
        await new Promise<void>((resolve) => {
          execFile('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
            windowsHide: true, timeout: 4_000,
          }, () => resolve());
        });
      }
      if (child.exitCode === null && child.signalCode === null) child.kill();
    }
    await connection.closed;
  })();
}

function errorCode(value: unknown, fallback: string): string {
  return typeof value === 'string' && /^[a-z][a-z_]{0,63}$/.test(value) ? value : fallback;
}

export class Backend extends EventEmitter {
  status: ProcessStatus = { state: 'stopped', error: null, session: 0 };
  private connection?: Connection;
  private nextId = 0;

  async start(executable: string, args: string[], cwd: string): Promise<void> {
    if (this.connection) throw new Error('backend_already_started');
    this.status = { state: 'starting', error: null, session: this.status.session + 1 };
    this.emit('status', this.status);
    let child: ChildProcessWithoutNullStreams;
    try {
      child = spawn(executable, args, { cwd, windowsHide: true, stdio: 'pipe' });
    } catch {
      this.setStatus('failed', 'python_start_failed');
      throw new Error('python_start_failed');
    }
    const ready = Promise.withResolvers<unknown>();
    const closed = Promise.withResolvers<void>();
    const connection = { child, ready, closed: closed.promise, pending: new Map<number, Reply>() };
    this.connection = connection;
    child.stderr.resume();
    child.stdin.on('error', () => {
      if (this.status.state === 'running') this.fail(connection, 'backend_exited');
    });
    child.on('error', () => this.fail(connection, 'python_start_failed'));
    const finish = () => {
      if (this.connection === connection) {
        this.connection = undefined;
        if (this.status.state === 'stopping') this.setStatus('stopped');
        else if (this.status.state !== 'failed') this.setStatus('failed', 'backend_exited');
        this.rejectPending(connection, this.status.error ?? 'backend_not_running');
      }
      closed.resolve();
    };
    let drainTimer: ReturnType<typeof setTimeout> | undefined;
    child.once('exit', () => {
      // A descendant can keep the pipes open after the interpreter exits.
      drainTimer = setTimeout(() => {
        child.stdin.destroy();
        child.stdout.destroy();
        child.stderr.destroy();
        finish();
      }, 250);
      if (this.status.state === 'running') this.fail(connection, 'backend_exited');
    });
    child.once('close', () => {
      clearTimeout(drainTimer);
      finish();
    });
    this.readFrames(connection);
    try {
      await deadline(ready.promise, 15_000, 'startup_timeout');
    } catch (error) {
      this.fail(connection, (error as Error).message);
      await terminate(connection);
      throw error;
    }
  }

  request(op: 'inspect' | 'send_chat' | 'set_scene' | 'shutdown', text?: string): Promise<unknown> {
    const connection = this.connection;
    if (!connection || (this.status.state !== 'running' &&
        !(op === 'shutdown' && this.status.state === 'stopping'))) {
      return Promise.reject(new Error('backend_not_running'));
    }
    const id = ++this.nextId;
    const response = Promise.withResolvers<unknown>();
    connection.pending.set(id, response);
    connection.child.stdin.write(JSON.stringify({ id, op, text }) + '\n', (error) => {
      if (error) response.reject(new Error('backend_exited'));
    });
    return deadline(response.promise, REQUEST_TIMEOUT, 'request_timeout')
      .finally(() => connection.pending.delete(id));
  }

  async stop(): Promise<Inspection | undefined> {
    const connection = this.connection;
    if (!connection) {
      this.setStatus('stopped');
      return;
    }
    const running = this.status.state === 'running';
    this.setStatus('stopping');
    try {
      if (!running) {
        await terminate(connection);
        return;
      }
      const [inspection] = await Promise.all([
        this.request('shutdown'),
        deadline(connection.closed, REQUEST_TIMEOUT, 'shutdown_timeout'),
      ]);
      return (inspection ?? undefined) as Inspection | undefined;
    } catch {
      await terminate(connection);
    }
  }

  private readFrames(connection: Connection) {
    const decoder = new TextDecoder('utf-8', { fatal: true });
    let remainder = Buffer.alloc(0);
    connection.child.stdout.on('data', (chunk: Buffer) => {
      if (this.connection !== connection || this.status.state === 'failed') return;
      const data = remainder.length ? Buffer.concat([remainder, chunk]) : chunk;
      try {
        let start = 0;
        let end: number;
        while ((end = data.indexOf(10, start)) !== -1) {
          if (end - start > FRAME_LIMIT) throw new Error();
          this.receive(connection, JSON.parse(decoder.decode(data.subarray(start, end))));
          if (connection.terminating) return;
          start = end + 1;
        }
        remainder = Buffer.from(data.subarray(start));
        if (remainder.length > FRAME_LIMIT) throw new Error();
      } catch {
        this.fail(connection, 'invalid_backend_frame');
      }
    });
  }

  private receive(connection: Connection, frame: Record<string, unknown>) {
    if (frame.type === 'ready' && frame.version === 1 && this.status.state === 'starting') {
      this.setStatus('running');
      connection.ready.resolve(undefined);
    } else if (frame.type === 'fatal') {
      this.fail(connection, errorCode(frame.error, 'startup_failed'));
    } else if (frame.type === 'response' && typeof frame.ok === 'boolean') {
      const reply = typeof frame.id === 'number' ? connection.pending.get(frame.id) : undefined;
      if (frame.ok) reply?.resolve(frame.result);
      else reply?.reject(new Error(errorCode(frame.error, 'operation_failed')));
    } else if (frame.type === 'output' && frame.output && typeof frame.output === 'object') {
      this.emit('output', frame.output, this.status.session);
    } else {
      throw new Error();
    }
  }

  private fail(connection: Connection, code: string) {
    if (this.connection !== connection || this.status.state === 'failed') return;
    if (this.status.state !== 'stopping') this.setStatus('failed', code);
    this.rejectPending(connection, code);
    void terminate(connection);
  }

  private rejectPending(connection: Connection, code: string) {
    const error = new Error(code);
    connection.ready.reject(error);
    for (const reply of connection.pending.values()) reply.reject(error);
    connection.pending.clear();
  }

  private setStatus(state: ProcessStatus['state'], error: string | null = null) {
    this.status = { ...this.status, state, error };
    this.emit('status', this.status);
  }
}
