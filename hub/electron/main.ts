import { existsSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { app, BrowserWindow, ipcMain, type IpcMainInvokeEvent } from 'electron';
import type { Control, ControlResult, Settings } from '../contract';
import { Backend } from './backend';

const root = resolve(__dirname, '../../..');
const backend = new Backend();
const venvPython = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
const bundledPath = join(root, venvPython);
const defaults: Settings = {
  backend: 'luna',
  python: existsSync(bundledPath) ? bundledPath : 'python',
  bun: 'bun',
  db: '',
};

let window: BrowserWindow | undefined;
let settings = defaults;
let controlQueue = Promise.resolve();
let quitting = false;
let stoppedForQuit = false;

function validatedSettings(value: unknown): Settings {
  if (!value || typeof value !== 'object') throw new Error('invalid_settings');
  const { backend, python, bun, db } = value as Partial<Settings>;
  if (backend !== 'fake' && backend !== 'luna') throw new Error('invalid_settings');
  return { backend, python: settingPath(python, defaults.python),
    bun: settingPath(bun, defaults.bun), db: settingPath(db, '') };
}

function settingPath(value: unknown, fallback: string): string {
  if (typeof value !== 'string' || value.length > 4096 || /[\x00-\x1f]/.test(value)) {
    throw new Error('invalid_settings');
  }
  return value.trim() || fallback;
}

function checkedText(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error('invalid_text');
  if (Buffer.byteLength(value, 'utf8') > 8 * 1024) throw new Error('text_too_large');
  return value;
}

function settingsPath(): string {
  return join(app.getPath('userData'), 'hub-settings.json');
}

async function control(action: Control): Promise<ControlResult> {
  if (action !== 'start' && action !== 'stop' && action !== 'restart') {
    throw new Error('invalid_request');
  }
  const operation = controlQueue.then(async () => {
    const inspection = action !== 'start' || backend.status.state === 'failed'
      ? await backend.stop()
      : undefined;
    if (action !== 'stop' && backend.status.state === 'stopped' && !quitting) {
      const { backend: kind, python, bun, db } = settings;
      const database = resolve(root, db || `.data/hub-${kind}.sqlite3`);
      const executable = python.includes('/') || python.includes('\\') ? resolve(root, python) : python;
      try {
        await backend.start(executable, ['-X', 'utf8', '-m', 'vtuber.hub',
          '--backend', kind, '--db', database, '--bun', bun], root);
      } catch {
        // The failed status carries the sanitized reason to the window.
      }
    }
    return action === 'stop' && inspection ? { ...backend.status, inspection } : backend.status;
  });
  controlQueue = operation.then(() => undefined, () => undefined);
  return operation;
}

function handle(channel: string, handler: (value: unknown) => unknown) {
  ipcMain.handle(`hub:${channel}`, (event: IpcMainInvokeEvent, value: unknown) => {
    if (event.sender !== window?.webContents || event.senderFrame !== event.sender.mainFrame) {
      throw new Error('invalid_request');
    }
    return handler(value);
  });
}

function createWindow() {
  window = new BrowserWindow({
    width: 1580,
    height: 960,
    minWidth: 390,
    minHeight: 540,
    title: 'Liac VTuber Hub',
    backgroundColor: '#10111a',
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.session.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  window.on('closed', () => { window = undefined; });
  void window.loadFile(join(root, 'hub', 'dist', 'index.html')).catch(() => app.quit());
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (window?.isMinimized()) window.restore();
    window?.focus();
  });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', (event) => {
    if (stoppedForQuit) return;
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    void control('stop').finally(() => {
      stoppedForQuit = true;
      app.quit();
    });
  });
  void app.whenReady().then(() => {
    try {
      settings = validatedSettings(JSON.parse(readFileSync(settingsPath(), 'utf8')));
    } catch {
      settings = defaults;
    }
    handle('status', () => backend.status);
    handle('settings', () => settings);
    handle('save-settings', (value) => {
      const next = validatedSettings(value);
      const file = settingsPath();
      try {
        writeFileSync(`${file}.tmp`, JSON.stringify(next), 'utf8');
        renameSync(`${file}.tmp`, file);
      } catch {
        throw new Error('settings_write_failed');
      }
      settings = next;
      return settings;
    });
    handle('control', (value) => control(value as Control));
    handle('inspect', () => backend.request('inspect'));
    handle('send-chat', (value) => backend.request('send_chat', checkedText(value)));
    handle('set-scene', (value) => backend.request('set_scene', checkedText(value)));
    backend.on('status', (status) => window?.webContents.send('hub:status-changed', status));
    backend.on('output', (output, session) => window?.webContents.send('hub:output', output, session));
    createWindow();
  });
}
