const assert = require('node:assert/strict');
const { once } = require('node:events');
const test = require('node:test');
const { Backend } = require('../dist-electron/electron/backend.js');

const child = String.raw`
const readline = require('node:readline');
const send = (frame) => console.log(JSON.stringify(frame));
send({type:'ready',version:1});
readline.createInterface({input:process.stdin}).on('line', (line) => {
  const {id,op,text} = JSON.parse(line);
  if (op === 'inspect') return send({type:'response',id,ok:true,result:{ready:true}});
  if (op === 'shutdown') {
    send({type:'response',id,ok:true,result:{activity:[],dialogue:[]}});
    process.exit(0);
  }
  if (text === 'crash') process.exit(7);
  if (text === 'oversize') return process.stdout.write('x'.repeat(1024 * 1024 + 1));
  send({type:'response',id,ok:true,result:{turn_id:'test-turn'}});
  const output = Buffer.from(JSON.stringify({type:'output',output:{kind:'reply.delta',turn_id:'test-turn',text,delta_index:1,character_id:'primary',revision:0}}) + '\n');
  const split = output.indexOf(Buffer.from('🌙')) + 1;
  process.stdout.write(output.subarray(0, split));
  setImmediate(() => process.stdout.write(output.subarray(split)));
});
`;

function start(backend, source = child) {
  return backend.start(process.execPath, ['-e', source], process.cwd());
}

test('starts, correlates responses, decodes streamed Unicode, and stops gracefully', async (t) => {
  const backend = new Backend();
  t.after(() => backend.stop());
  await start(backend);
  const provisional = once(backend, 'output');
  assert.deepEqual(await backend.request('inspect'), { ready: true });
  assert.deepEqual(await backend.request('send_chat', 'Привіт 🌙'), { turn_id: 'test-turn' });
  const [output, session] = await provisional;
  assert.equal(output.text, 'Привіт 🌙');
  assert.equal(session, backend.status.session);
  assert.deepEqual(await backend.stop(), { activity: [], dialogue: [] });
  assert.equal(backend.status.state, 'stopped');
});

test('unexpected exit rejects requests and permits a clean restart', async (t) => {
  const backend = new Backend();
  t.after(() => backend.stop());
  await start(backend);
  const session = backend.status.session;
  await assert.rejects(backend.request('send_chat', 'crash'), /backend_exited/);
  assert.equal(backend.status.state, 'failed');
  await start(backend);
  assert.ok(backend.status.session > session);
  assert.deepEqual(await backend.request('inspect'), { ready: true });
});

test('missing Python and structured startup failure reach the process status', async (t) => {
  const backend = new Backend();
  t.after(() => backend.stop());
  await assert.rejects(backend.start('liac-nonexistent-python.exe', [], process.cwd()), /python_start_failed/);
  assert.equal(backend.status.error, 'python_start_failed');
  await assert.rejects(start(backend, "console.log(JSON.stringify({type:'fatal',error:'bun_not_found'}))"), /bun_not_found/);
  assert.equal(backend.status.error, 'bun_not_found');
});

test('oversized unterminated child frames fail and clean up the process', async (t) => {
  const backend = new Backend();
  t.after(() => backend.stop());
  await start(backend);
  await assert.rejects(backend.request('send_chat', 'oversize'), /invalid_backend_frame/);
  assert.equal(backend.status.state, 'failed');
});

test('shutdown reaps an unresponsive Windows backend and its child', {
  skip: process.platform !== 'win32',
}, async (t) => {
  const backend = new Backend();
  t.after(() => backend.stop());
  await start(backend, `
    const child = require('node:child_process').spawn(process.execPath,
      ['-e', 'setInterval(() => {}, 1000)'], {stdio:'ignore', windowsHide:true});
    console.log('{"type":"ready","version":1}');
    require('node:readline').createInterface({input:process.stdin}).on('line', (line) => {
      const {id,op} = JSON.parse(line);
      if (op === 'inspect') console.log(JSON.stringify({type:'response',id,ok:true,result:child.pid}));
    });
  `);
  const pid = await backend.request('inspect');
  assert.ok(Number.isInteger(pid));
  await backend.stop();
  assert.equal(backend.status.state, 'stopped');
  assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
});

test('an exited backend cannot hold the session open through inherited pipes', async (t) => {
  const backend = new Backend();
  let pid;
  t.after(async () => {
    if (pid) {
      try { process.kill(pid); } catch (error) { if (error.code !== 'ESRCH') throw error; }
    }
    await backend.stop();
  });
  await start(backend, `
    const child = require('node:child_process').spawn(process.execPath,
      ['-e', 'setTimeout(() => {}, 4000)'], {stdio:'inherit', windowsHide:true});
    console.log('{"type":"ready","version":1}');
    require('node:readline').createInterface({input:process.stdin}).on('line', (line) => {
      const {id,op} = JSON.parse(line);
      if (op === 'inspect') console.log(JSON.stringify({type:'response',id,ok:true,result:child.pid}));
      else process.exit(7);
    });
  `);
  pid = await backend.request('inspect');
  const startTime = Date.now();
  await assert.rejects(backend.request('send_chat', 'crash'), /backend_exited/);
  assert.ok(Date.now() - startTime < 2000, 'detects exit before the descendant closes its pipe');
  await backend.stop();
  assert.ok(Date.now() - startTime < 2000, 'cleans up the session without the pipe closing naturally');
});
