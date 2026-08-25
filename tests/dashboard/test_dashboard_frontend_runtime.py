import subprocess
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "dashboard" / "web"


RUNTIME_CHECK = r'''
const fs = require('fs');
const esbuild = require('esbuild');

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function compile(path, loader) {
  return esbuild.transformSync(fs.readFileSync(path, 'utf8'), {
    loader,
    format: 'cjs',
    target: 'es2020',
    jsx: 'automatic',
  }).code;
}

function loadModule(code, modules) {
  const module = { exports: {} };
  const requireModule = (name) => modules[name] || new Proxy({}, {
    get: (_target, property) => String(property),
  });
  new Function('require', 'module', 'exports', code)(requireModule, module, module.exports);
  return module.exports;
}

function createHooks() {
  const values = [];
  let cursor = 0;
  let firstRender = true;
  const effects = [];
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in values)) values[index] = initial;
      return [values[index], (next) => {
        values[index] = typeof next === 'function' ? next(values[index]) : next;
      }];
    },
    useEffect(effect) {
      if (firstRender) effects.push(effect);
    },
  };
  return {
    react,
    render(component) {
      cursor = 0;
      const tree = component();
      if (firstRender) {
        firstRender = false;
        effects.splice(0).forEach((effect) => effect());
      }
      return tree;
    },
  };
}

const jsxRuntime = {
  jsx: (type, props) => ({ type, props: props || {} }),
  jsxs: (type, props) => ({ type, props: props || {} }),
  Fragment: 'Fragment',
};

function findElementWithText(node, text) {
  if (!node || typeof node !== 'object') return null;
  if (node.props && node.props.children === text) return node;
  const children = node.props && node.props.children;
  const entries = Array.isArray(children) ? children : [children];
  for (const child of entries) {
    const found = findElementWithText(child, text);
    if (found) return found;
  }
  return null;
}

function findElementByType(node, type) {
  if (!node || typeof node !== 'object') return null;
  if (node.type === type) return node;
  const children = node.props && node.props.children;
  const entries = Array.isArray(children) ? children : [children];
  for (const child of entries) {
    const found = findElementByType(child, type);
    if (found) return found;
  }
  return null;
}

async function tick() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function main() {
  const listeners = {};
  global.localStorage = {
    values: { arteta_dashboard_token: 'expired-token' },
    getItem(key) { return this.values[key] || null; },
    setItem(key, value) { this.values[key] = String(value); },
    removeItem(key) { delete this.values[key]; },
  };
  global.Event = class Event { constructor(type) { this.type = type; } };
  global.window = {
    addEventListener(type, handler) { (listeners[type] || (listeners[type] = [])).push(handler); },
    removeEventListener(type, handler) {
      listeners[type] = (listeners[type] || []).filter((item) => item !== handler);
    },
    dispatchEvent(event) { (listeners[event.type] || []).forEach((handler) => handler(event)); },
  };
  let fetchResponse = { status: 200, json: async () => ({ ok: true, data: { token: 'fresh-token' } }) };
  global.fetch = async () => fetchResponse;

  const client = loadModule(compile('src/api/client.ts', 'ts'), {});
  const loginHooks = createHooks();
  let successfulLogins = 0;
  const login = loadModule(compile('src/pages/LoginPage.tsx', 'tsx'), {
    react: loginHooks.react,
    'react/jsx-runtime': jsxRuntime,
    '../api/client': client,
  });
  let loginTree = loginHooks.render(() => login.LoginPage({ onLogin: () => { successfulLogins += 1; } }));
  findElementByType(loginTree, 'input').props.onChange({ target: { value: 'correct-password' } });
  loginTree = loginHooks.render(() => login.LoginPage({ onLogin: () => { successfulLogins += 1; } }));
  await findElementByType(loginTree, 'form').props.onSubmit({ preventDefault() {} });
  check(localStorage.getItem('arteta_dashboard_token') === 'fresh-token', 'successful login must save its token');
  check(successfulLogins === 1, 'successful login must enter the dashboard exactly once');

  const failedLoginHooks = createHooks();
  let failedLoginCallbacks = 0;
  const failedLogin = loadModule(compile('src/pages/LoginPage.tsx', 'tsx'), {
    react: failedLoginHooks.react,
    'react/jsx-runtime': jsxRuntime,
    '../api/client': client,
  });
  fetchResponse = { status: 401, json: async () => ({ ok: false }) };
  let failedLoginTree = failedLoginHooks.render(() => failedLogin.LoginPage({ onLogin: () => { failedLoginCallbacks += 1; } }));
  findElementByType(failedLoginTree, 'input').props.onChange({ target: { value: 'wrong-password' } });
  failedLoginTree = failedLoginHooks.render(() => failedLogin.LoginPage({ onLogin: () => { failedLoginCallbacks += 1; } }));
  await findElementByType(failedLoginTree, 'form').props.onSubmit({ preventDefault() {} });
  failedLoginTree = failedLoginHooks.render(() => failedLogin.LoginPage({ onLogin: () => { failedLoginCallbacks += 1; } }));
  check(failedLoginCallbacks === 0, 'failed login must not enter the dashboard');
  check(JSON.stringify(failedLoginTree).includes('UNAUTHORIZED'), 'failed login must render an error');

  client.setToken('fresh-token');
  const appHooks = createHooks();
  const app = loadModule(compile('src/App.tsx', 'tsx'), {
    react: appHooks.react,
    'react/jsx-runtime': jsxRuntime,
    './api/client': client,
    './pages/LoginPage': { LoginPage: 'LoginPage' },
  });
  let appTree = appHooks.render(app.App);
  check(appTree.type === 'main', 'App must start on the launch page');
  findElementWithText(appTree, '开始').props.onClick();
  appTree = appHooks.render(app.App);
  check(appTree.type === 'LoginPage', 'launch action must show LoginPage');
  appTree.props.onLogin();
  appTree = appHooks.render(app.App);
  check(appTree.type === 'Shell', 'successful login callback must show Shell');
  fetchResponse = { status: 401, json: async () => ({ ok: false }) };
  await client.apiGet('/api/config/providers').catch((error) => {
    check(error.message === 'UNAUTHORIZED', '401 must reject as unauthorized');
  });
  check(!localStorage.getItem('arteta_dashboard_token'), '401 must clear the stale token');
  appTree = appHooks.render(app.App);
  check(appTree.type === 'LoginPage', '401 must return App to LoginPage');

  let calls = 0;
  const configClient = {
    apiGet: async () => {
      calls += 1;
      if (calls === 1) throw new Error('provider endpoint unavailable');
      return [{ id: 'chat', label: 'Chat', configured: true, fields: [] }];
    },
    apiPost: async () => ({}),
  };
  const configHooks = createHooks();
  const config = loadModule(compile('src/pages/ConfigPage.tsx', 'tsx'), {
    react: configHooks.react,
    'react/jsx-runtime': jsxRuntime,
    '../api/client': configClient,
    '../components/ConfirmDialog': { ConfirmDialog: 'ConfirmDialog' },
  });
  configHooks.render(config.ConfigPage);
  await tick();
  let configTree = configHooks.render(config.ConfigPage);
  check(JSON.stringify(configTree).includes('provider endpoint unavailable'), 'load failure must be rendered');
  const retry = findElementWithText(configTree, 'Retry loading configuration');
  check(retry && typeof retry.props.onClick === 'function', 'load failure must provide retry action');
  retry.props.onClick();
  await tick();
  configTree = configHooks.render(config.ConfigPage);
  check(JSON.stringify(configTree).includes('Chat'), 'retry must render recovered provider data');
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
'''


def test_dashboard_frontend_runtime_auth_and_config_recovery():
    if shutil.which("node") is None:
        pytest.skip("Node.js is required for Dashboard frontend runtime checks")
    esbuild_probe = subprocess.run(
        ["node", "-e", "require.resolve('esbuild')"],
        cwd=str(WEB_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if esbuild_probe.returncode != 0:
        pytest.skip("Dashboard frontend dependencies are required for runtime checks")
    result = subprocess.run(
        ["node", "-e", RUNTIME_CHECK],
        cwd=str(WEB_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
