import { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';

type Group = {
  group_id: string;
  group_name?: string;
  user_count: number;
  message_count: number;
  last_activity: string | null;
  memory_password_enabled?: boolean;
};

type MemoryRow = {
  id: string;
  document: string;
  preview?: string;
  metadata: Record<string, unknown>;
  distance?: number | null;
};

export function MemoriesPage() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupId, setGroupId] = useState('');
  const [query, setQuery] = useState('');
  const [rows, setRows] = useState<MemoryRow[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pendingDelete, setPendingDelete] = useState<string[] | null>(null);
  const [error, setError] = useState('');
  const [groupPasswords, setGroupPasswords] = useState<Record<string, string>>({});
  const [passwordInput, setPasswordInput] = useState('');

  useEffect(() => {
    void loadGroups();
  }, []);

  const selectedGroup = groups.find(group => group.group_id === groupId);
  const selectedGroupNeedsPassword = Boolean(selectedGroup?.memory_password_enabled);
  const selectedGroupPassword = groupPasswords[groupId] || '';
  const canAccessSelectedGroup = Boolean(groupId) && (!selectedGroupNeedsPassword || Boolean(selectedGroupPassword));

  function passwordHeader(targetGroupId: string): Record<string, string> {
    const password = groupPasswords[targetGroupId] || '';
    return password ? { 'X-Group-Password': password } : {};
  }

  function groupLabel(group: Group | undefined): string {
    if (!group) return groupId ? `群号 ${groupId}` : '';
    const name = group.group_name?.trim();
    return name ? `${name}（群号 ${group.group_id}）` : `群号 ${group.group_id}`;
  }

  async function loadGroups() {
    try {
      const loadedGroups = await apiGet<Group[]>('/api/groups');
      setGroups(loadedGroups);
      if (loadedGroups.length > 0) {
        await selectGroup(loadedGroups[0].group_id, loadedGroups);
      }
    } catch (err) {
      setError(String(err));
    }
  }

  async function load(targetGroupId = groupId) {
    if (!targetGroupId) return;
    setError('');
    const targetGroup = groups.find(group => group.group_id === targetGroupId);
    if (targetGroup?.memory_password_enabled && !groupPasswords[targetGroupId]) {
      setRows([]);
      setSelected(new Set());
      return;
    }
    const params = new URLSearchParams({ group_id: targetGroupId, limit: '100' });
    try {
      setRows(await apiGet<MemoryRow[]>(`/api/memories?${params.toString()}`, passwordHeader(targetGroupId)));
      setSelected(new Set());
    } catch (err) {
      setRows([]);
      setSelected(new Set());
      setError(String(err));
    }
  }

  async function selectGroup(nextGroupId: string, availableGroups = groups) {
    setGroupId(nextGroupId);
    setPasswordInput('');
    const nextGroup = availableGroups.find(group => group.group_id === nextGroupId);
    if (nextGroup?.memory_password_enabled && !groupPasswords[nextGroupId]) {
      setRows([]);
      setSelected(new Set());
      return;
    }
    if (query.trim()) {
      await search(nextGroupId);
    } else {
      await load(nextGroupId);
    }
  }

  async function unlockGroup() {
    const password = passwordInput.trim();
    if (!groupId || !password) return;
    const nextPasswords = { ...groupPasswords, [groupId]: password };
    setGroupPasswords(nextPasswords);
    setPasswordInput('');
    const params = new URLSearchParams({ group_id: groupId, limit: '100' });
    try {
      setRows(await apiGet<MemoryRow[]>(`/api/memories?${params.toString()}`, { 'X-Group-Password': password }));
      setSelected(new Set());
      setError('');
    } catch (err) {
      setRows([]);
      setSelected(new Set());
      setGroupPasswords(groupPasswords);
      setError('群组密码错误或未输入');
    }
  }

  async function search(targetGroupId = groupId) {
    if (!targetGroupId) return;
    if (!query.trim()) {
      await load(targetGroupId);
      return;
    }
    const targetGroup = groups.find(group => group.group_id === targetGroupId);
    if (targetGroup?.memory_password_enabled && !groupPasswords[targetGroupId]) {
      setRows([]);
      setSelected(new Set());
      return;
    }
    const params = new URLSearchParams({ q: query, group_id: targetGroupId, limit: '20' });
    try {
      setRows(await apiGet<MemoryRow[]>(`/api/memories/search?${params.toString()}`, passwordHeader(targetGroupId)));
      setSelected(new Set());
      setError('');
    } catch (err) {
      setRows([]);
      setSelected(new Set());
      setError(String(err));
    }
  }

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  async function confirmDelete() {
    if (!pendingDelete || !groupId) return;
    await apiPost<{ deleted: number }>('/api/memories/delete', {
      group_id: groupId,
      ids: pendingDelete,
      password: groupPasswords[groupId] || ''
    });
    setPendingDelete(null);
    await load();
  }

  return (
    <div className="memory-group-layout">
      <section className="panel page-panel memory-group-panel">
        <h2>群组分类</h2>
        {groups.length === 0 && <p className="muted">暂无群组</p>}
        {groups.map(group => (
          <button key={group.group_id} onClick={() => selectGroup(group.group_id)} className={groupId === group.group_id ? 'selected-row' : ''}>
            <span>{groupLabel(group)}{group.memory_password_enabled ? ' · 已加密' : ''}</span>
            <small>{group.user_count} 名用户 · {group.message_count} 条消息</small>
          </button>
        ))}
      </section>

      <div className="stack memory-list-panel">
        <section className="panel page-panel toolbar">
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder={groupId ? `在 ${groupLabel(selectedGroup)} 内语义搜索` : '请先选择群组'} disabled={!canAccessSelectedGroup} />
          <button disabled={!canAccessSelectedGroup} onClick={() => search()}>搜索</button>
          <button disabled={!canAccessSelectedGroup} onClick={() => load()}>刷新</button>
          <button disabled={!canAccessSelectedGroup || selected.size === 0} onClick={() => setPendingDelete(Array.from(selected))}>删除选中</button>
        </section>

        {selectedGroupNeedsPassword && !selectedGroupPassword && (
          <section className="panel page-panel toolbar">
            <input type="password" value={passwordInput} onChange={event => setPasswordInput(event.target.value)} placeholder={`输入 ${groupLabel(selectedGroup)} 的记忆密码`} />
            <button onClick={unlockGroup}>解锁群组记忆</button>
          </section>
        )}

        {error && <section className="panel page-panel error-text">{error}</section>}
        <section className="panel page-panel table-panel">
          <h2>{groupId ? `Chroma 记忆 · ${groupLabel(selectedGroup)}` : 'Chroma 记忆 · 请选择群组'}</h2>
          {!canAccessSelectedGroup ? <p className="muted">该群组记忆需要密码后查看</p> : rows.length === 0 ? <p className="muted">暂无记忆</p> : rows.map(row => (
            <article key={row.id} className="memory-row">
              <label><input type="checkbox" checked={selected.has(row.id)} onChange={() => toggle(row.id)} /> {row.id}</label>
              <p>{row.preview || row.document.slice(0, 160)}</p>
              <small>{JSON.stringify(row.metadata)}{row.distance !== undefined && row.distance !== null ? ` · 距离 ${row.distance}` : ''}</small>
              <button onClick={() => setPendingDelete([row.id])}>删除</button>
            </article>
          ))}
        </section>
      </div>

      {pendingDelete && (
        <ConfirmDialog title="删除记忆" message={`确定删除 ${pendingDelete.length} 条 Chroma 记忆记录吗？`} onCancel={() => setPendingDelete(null)} onConfirm={confirmDelete} />
      )}
    </div>
  );
}
