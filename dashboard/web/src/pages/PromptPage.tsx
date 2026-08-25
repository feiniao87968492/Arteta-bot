import { useEffect, useMemo, useState } from 'react';
import { apiDelete, apiGet, apiPost, apiPut } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';

type PromptEntry = {
  key: string;
  title: string;
  category: string;
  content: string;
  variables: string[];
  enabled: boolean;
  builtin: boolean;
};

type PendingAction =
  | { type: 'save' }
  | { type: 'restore' }
  | { type: 'delete' }
  | null;

const emptyDraft: PromptEntry = {
  key: '',
  title: '',
  category: '自定义',
  content: '',
  variables: [],
  enabled: true,
  builtin: false
};

export function PromptPage() {
  const [entries, setEntries] = useState<PromptEntry[]>([]);
  const [selectedKey, setSelectedKey] = useState('');
  const [draft, setDraft] = useState<PromptEntry>(emptyDraft);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState<PendingAction>(null);

  useEffect(() => { void load(); }, []);

  async function load(nextKey?: string) {
    const data = await apiGet<PromptEntry[]>('/api/prompts');
    setEntries(data);
    const key = nextKey || selectedKey || data[0]?.key || '';
    const selected = data.find(entry => entry.key === key) || data[0];
    if (selected) {
      setSelectedKey(selected.key);
      setDraft({ ...selected, variables: [...selected.variables] });
    }
  }

  const categories = useMemo(() => {
    const grouped = new Map<string, PromptEntry[]>();
    for (const entry of entries) {
      const list = grouped.get(entry.category) || [];
      list.push(entry);
      grouped.set(entry.category, list);
    }
    return Array.from(grouped.entries());
  }, [entries]);

  const dirty = useMemo(() => {
    const original = entries.find(entry => entry.key === draft.key);
    return JSON.stringify(original || emptyDraft) !== JSON.stringify(draft);
  }, [draft, entries]);

  function select(entry: PromptEntry) {
    setSelectedKey(entry.key);
    setDraft({ ...entry, variables: [...entry.variables] });
    setMessage('');
    setError('');
  }

  function createNew() {
    setSelectedKey('');
    setDraft({ ...emptyDraft });
    setMessage('');
    setError('');
  }

  async function save() {
    try {
      setError('');
      const exists = entries.some(entry => entry.key === draft.key);
      const payload = {
        key: draft.key,
        title: draft.title,
        category: draft.category,
        content: draft.content,
        variables: draft.variables,
        enabled: draft.enabled
      };
      const saved = exists
        ? await apiPut<PromptEntry>(`/api/prompts/${encodeURIComponent(draft.key)}`, payload)
        : await apiPost<PromptEntry>('/api/prompts', payload);
      setMessage(`${saved.title} 已保存`);
      setPending(null);
      await load(saved.key);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
      setPending(null);
    }
  }

  async function restore() {
    try {
      setError('');
      const restored = await apiPost<PromptEntry>(`/api/prompts/${encodeURIComponent(draft.key)}/restore`, {});
      setMessage(`${restored.title} 已恢复默认`);
      setPending(null);
      await load(restored.key);
    } catch (err) {
      setError(err instanceof Error ? err.message : '恢复失败');
      setPending(null);
    }
  }

  async function remove() {
    try {
      setError('');
      await apiDelete<{ key: string }>(`/api/prompts/${encodeURIComponent(draft.key)}`);
      setMessage(`${draft.title || draft.key} 已删除`);
      setPending(null);
      await load('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
      setPending(null);
    }
  }

  const variableText = draft.variables.join(', ');
  const confirmMessage = pending?.type === 'save'
    ? `确定保存 ${draft.title || draft.key} 吗？线上机器人可能在重启后使用这段 prompt。`
    : pending?.type === 'restore'
      ? `确定把 ${draft.title || draft.key} 恢复为代码默认 prompt 吗？`
      : `确定删除 ${draft.title || draft.key} 吗？`;

  return (
    <div className="prompt-layout">
      <section className="panel prompt-sidebar">
        <div className="prompt-sidebar-header">
          <h2>Prompt 人设</h2>
          <button onClick={createNew}>新增</button>
        </div>
        <p className="muted">只有内置 key 会被机器人运行时调用；自定义 key 先作为文本资产保存。</p>
        {categories.map(([category, items]) => (
          <div key={category} className="prompt-category">
            <h3>{category}</h3>
            {items.map(entry => (
              <button key={entry.key} className={entry.key === selectedKey ? 'prompt-item active' : 'prompt-item'} onClick={() => select(entry)}>
                <strong>{entry.title}</strong>
                <small>{entry.key}{entry.enabled ? '' : ' / disabled'}</small>
              </button>
            ))}
          </div>
        ))}
      </section>

      <section className="panel page-panel prompt-editor">
        <div className="prompt-editor-title">
          <div>
            <p className="mission-kicker">PROMPT REGISTRY</p>
            <h2>{draft.key ? draft.title || draft.key : '新增 Prompt'}</h2>
          </div>
          {draft.builtin && <span className="prompt-badge">内置运行时 key</span>}
        </div>
        {message && <p className="status-ok">{message}</p>}
        {error && <p className="status-error">{error}</p>}
        <div className="prompt-form-grid">
          <label>Key<input value={draft.key} disabled={draft.builtin || entries.some(entry => entry.key === draft.key)} onChange={event => setDraft(current => ({ ...current, key: event.target.value }))} /></label>
          <label>标题<input value={draft.title} onChange={event => setDraft(current => ({ ...current, title: event.target.value }))} /></label>
          <label>分组<input value={draft.category} onChange={event => setDraft(current => ({ ...current, category: event.target.value }))} /></label>
          <label>变量<input value={variableText} onChange={event => setDraft(current => ({ ...current, variables: event.target.value.split(',').map(item => item.trim()).filter(Boolean) }))} /></label>
        </div>
        <label className="prompt-enabled"><input type="checkbox" checked={draft.enabled} onChange={event => setDraft(current => ({ ...current, enabled: event.target.checked }))} /> 启用此条目覆盖代码默认 prompt</label>
        <textarea className="prompt-textarea" value={draft.content} onChange={event => setDraft(current => ({ ...current, content: event.target.value }))} placeholder="在这里编辑多行 prompt" />
        <div className="prompt-actions">
          <button disabled={!draft.key || !dirty} onClick={() => setPending({ type: 'save' })}>保存</button>
          <button disabled={!draft.builtin} onClick={() => setPending({ type: 'restore' })}>恢复默认</button>
          <button disabled={draft.builtin || !draft.key} onClick={() => setPending({ type: 'delete' })}>删除</button>
        </div>
      </section>

      {pending && (
        <ConfirmDialog title="确认 Prompt 操作" message={confirmMessage} onCancel={() => setPending(null)} onConfirm={pending.type === 'save' ? save : pending.type === 'restore' ? restore : remove} />
      )}
    </div>
  );
}
