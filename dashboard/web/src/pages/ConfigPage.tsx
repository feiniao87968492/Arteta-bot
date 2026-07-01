import { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';

type ConfigKey = { name: string; exists: boolean; masked: string };

export function ConfigPage() {
  const [keys, setKeys] = useState<ConfigKey[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<string | null>(null);
  const [message, setMessage] = useState('');

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

  return (
    <div className="stack">
      <section className="panel page-panel">
        <h2>配置密钥</h2>
        <p className="muted">现有密钥只显示脱敏值。更新密钥时请输入完整的新值。</p>
        {message && <p className="status-ok">{message}</p>}
        {keys.map(key => (
          <div key={key.name} className="config-row">
            <div>
              <strong>{key.name}</strong>
              <small>{key.exists ? key.masked : '未配置'}</small>
            </div>
            <input type="password" value={values[key.name] || ''} onChange={event => setValues(current => ({ ...current, [key.name]: event.target.value }))} placeholder="完整的新值" />
            <button disabled={!values[key.name]} onClick={() => setPending(key.name)}>保存</button>
          </div>
        ))}
      </section>
      {pending && (
        <ConfirmDialog title="保存密钥" message={`确定替换 ${pending} 吗？当前界面无法找回旧值。`} onCancel={() => setPending(null)} onConfirm={save} />
      )}
    </div>
  );
}
