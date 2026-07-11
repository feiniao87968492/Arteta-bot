import { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';

type ConfigKey = { name: string; exists: boolean; masked: string };
type ConfigTest = {
  name: string;
  effective: boolean;
  file_value: string;
  runtime_value: string;
  runtime_exists: boolean;
  requires_bot_restart: boolean;
  note: string;
};

export function ConfigPage() {
  const [keys, setKeys] = useState<ConfigKey[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<string | null>(null);
  const [restartPending, setRestartPending] = useState(false);
  const [restartBusy, setRestartBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [testResults, setTestResults] = useState<Record<string, ConfigTest>>({});

  useEffect(() => { void load(); }, []);

  async function load() {
    setKeys(await apiGet<ConfigKey[]>('/api/config/keys'));
  }

  async function save() {
    if (!pending) return;
    await apiPost<{ name: string }>('/api/config/keys', { name: pending, value: values[pending] || '' });
    setMessage(`${pending} 已保存`);
    setPending(null);
    setValues(current => ({ ...current, [pending]: '' }));
    await load();
  }

  async function testConfig(name: string) {
    const result = await apiGet<ConfigTest>(`/api/config/keys/${encodeURIComponent(name)}/test`);
    setTestResults(current => ({ ...current, [name]: result }));
    setMessage(result.effective ? `${name} 当前 Dashboard API 已生效` : `${name} 文件值与当前运行值不一致`);
  }

  async function restartBot() {
    setRestartBusy(true);
    try {
      await apiPost<{ service: string; returncode: number; stdout: string; stderr: string }>('/api/config/restart-bot', {});
      setMessage('QQ Bot 重启命令已发送');
    } finally {
      setRestartBusy(false);
      setRestartPending(false);
    }
  }

  return (
    <div className="stack">
      <section className="panel page-panel">
        <h2>配置密钥</h2>
        <p className="muted">现有密钥只显示脱敏值。更新密钥时请输入完整的新值。</p>
        <div className="inline-actions">
          <button disabled={restartBusy} onClick={() => setRestartPending(true)}>重启 QQ Bot</button>
          <small className="muted">重启后会重新读取配置文件。</small>
        </div>
        {message && <p className="status-ok">{message}</p>}
        {keys.map(key => (
          <div key={key.name} className="config-row">
            <div>
              <strong>{key.name}</strong>
              <small>{key.exists ? key.masked : '未配置'}</small>
              {testResults[key.name] && (
                <small>
                  测试：{testResults[key.name].effective ? 'Dashboard API 已生效' : '运行值不一致'}
                  {testResults[key.name].requires_bot_restart ? '；QQ Bot 需重启后生效' : ''}
                </small>
              )}
            </div>
            <input type="password" value={values[key.name] || ''} onChange={event => setValues(current => ({ ...current, [key.name]: event.target.value }))} placeholder="完整的新值" />
            <button disabled={!values[key.name]} onClick={() => setPending(key.name)}>保存</button>
            <button onClick={() => { void testConfig(key.name); }}>测试</button>
          </div>
        ))}
      </section>
      {pending && (
        <ConfirmDialog title="保存密钥" message={`确定替换 ${pending} 吗？当前界面无法找回旧值。`} onCancel={() => setPending(null)} onConfirm={save} />
      )}
      {restartPending && (
        <ConfirmDialog title="重启 QQ Bot" message="确定重启 arteta_bot 吗？重启后会重新读取配置文件，期间 QQ 群回复会短暂中断。" onCancel={() => setRestartPending(false)} onConfirm={restartBot} />
      )}
    </div>
  );
}
