import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';
import type { HubAPI, ProcessStatus, RuntimeOutput } from '../contract';

const api: HubAPI = {
  status: () => ipcRenderer.invoke('hub:status'),
  settings: () => ipcRenderer.invoke('hub:settings'),
  saveSettings: (settings) => ipcRenderer.invoke('hub:save-settings', settings),
  control: (action) => ipcRenderer.invoke('hub:control', action),
  inspect: () => ipcRenderer.invoke('hub:inspect'),
  sendChat: (text) => ipcRenderer.invoke('hub:send-chat', text),
  setScene: (text) => ipcRenderer.invoke('hub:set-scene', text),
  onStatus: (listener) => {
    const receive = (_event: IpcRendererEvent, status: ProcessStatus) => listener(status);
    ipcRenderer.on('hub:status-changed', receive);
    return () => { ipcRenderer.removeListener('hub:status-changed', receive); };
  },
  onOutput: (listener) => {
    const receive = (_event: IpcRendererEvent, output: RuntimeOutput, session: number) => listener(output, session);
    ipcRenderer.on('hub:output', receive);
    return () => { ipcRenderer.removeListener('hub:output', receive); };
  },
};

contextBridge.exposeInMainWorld('hub', api);
