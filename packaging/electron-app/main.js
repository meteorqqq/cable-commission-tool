const { app, BrowserWindow, Menu, shell } = require('electron');
const path = require('path');

const APP_URL = 'https://cable-commission-tool.streamlit.app/';
const APP_TITLE = '锐洋集团提成计算工具';

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
  return;
}

let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    title: APP_TITLE,
    icon: path.join(__dirname, 'assets', 'app.ico'),
    autoHideMenuBar: true,
    backgroundColor: '#FFFFFF',
    show: false,
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      devTools: false,
    },
  });

  Menu.setApplicationMenu(null);

  mainWindow.maximize();
  mainWindow.show();

  mainWindow.loadURL(APP_URL);

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\/(?:[\w.-]+\.)?streamlit(?:app)?\./i.test(url) ||
        /^https?:\/\/(?:[\w.-]+\.)?(?:googleapis|gstatic)\./i.test(url)) {
      return { action: 'allow' };
    }
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.webContents.on('page-title-updated', (e) => {
    e.preventDefault();
    mainWindow.setTitle(APP_TITLE);
  });
}

app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
