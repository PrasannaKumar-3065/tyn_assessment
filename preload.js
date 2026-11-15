const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('api', {
  on: (channel, cb) => ipcRenderer.on(channel, (_e, data) => cb(data)),
});
