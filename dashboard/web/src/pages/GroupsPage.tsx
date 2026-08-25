import { useEffect, useState } from 'react';
import { apiDelete, apiGet, apiPost, getToken } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';

type Group = { group_id: string; group_name?: string; user_count: number; message_count: number; last_activity: string | null; memory_password_enabled?: boolean };
type GroupSettings = { group_id: string; memory_password_enabled: boolean };
type GroupNameSettings = { group_id: string; group_name: string };
type User = { user_id: string; nickname: string; level: string; favorability: number; message_count: number };
type ProfileEntry = { id: string; key: string; value: string };

type UserDetail = {
  user_id: string;
  current_nickname: string;
  level: string;
  favorability: number;
  last_seen: string | number;
  nicknames: Array<Record<string, unknown>>;
  recent_messages: Array<Record<string, unknown>>;
  message_count: number;
  personality_profile: Record<string, unknown>;
  relations: Array<Record<string, unknown>>;
};

export function GroupsPage() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [selectedGroup, setSelectedGroup] = useState('');
  const [selectedUser, setSelectedUser] = useState('');
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [profileEntries, setProfileEntries] = useState<ProfileEntry[]>([]);
  const [groupPassword, setGroupPassword] = useState('');
  const [groupPasswords, setGroupPasswords] = useState<Record<string, string>>({});
  const [accessPassword, setAccessPassword] = useState('');
  const [editingGroupName, setEditingGroupName] = useState('');
  const [groupNameDraft, setGroupNameDraft] = useState('');
  const [pendingDelete, setPendingDelete] = useState(false);
  const [favorDraft, setFavorDraft] = useState('');
  const [favorDelta, setFavorDelta] = useState('');
  const [savingFavor, setSavingFavor] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    apiGet<Group[]>('/api/groups').then(setGroups).catch(err => setError(String(err)));
  }, []);

  const selectedGroupRecord = groups.find(group => group.group_id === selectedGroup);
  const selectedGroupNeedsPassword = Boolean(selectedGroupRecord?.memory_password_enabled);
  const selectedGroupPassword = groupPasswords[selectedGroup] || '';
  const canAccessSelectedGroup = Boolean(selectedGroup) && (!selectedGroupNeedsPassword || Boolean(selectedGroupPassword));

  function groupPasswordHeader(groupId: string): Record<string, string> {
    const password = groupPasswords[groupId] || '';
    return password ? { 'X-Group-Password': password } : {};
  }

  function groupLabel(group: Group | undefined): string {
    if (!group) return selectedGroup ? `群号 ${selectedGroup}` : '';
    const name = group.group_name?.trim();
    return name ? `${name}（群号 ${group.group_id}）` : `群号 ${group.group_id}`;
  }

  function updateGroupPasswordStatus(groupId: string, enabled: boolean) {
    setGroups(currentGroups => currentGroups.map(group => (group.group_id === groupId ? { ...group, memory_password_enabled: enabled } : group)));
  }

  function stringifyProfileValue(value: unknown): string {
    if (typeof value === 'string') return value;
    if (value === undefined) return '';
    return JSON.stringify(value, null, 2);
  }

  function profileRecordToEntries(profile: Record<string, unknown>): ProfileEntry[] {
    return Object.entries(profile || {}).map(([key, value], index) => ({ id: `${key}-${index}`, key, value: stringifyProfileValue(value) }));
  }

  function parseProfileValue(value: string): unknown {
    const text = value.trim();
    if (!text) return '';
    if (/^(\{|\[|true$|false$|null$|-?\d)/.test(text)) {
      try {
        return JSON.parse(text);
      } catch {
        return value;
      }
    }
    return value;
  }

  function profileEntriesToRecord(): Record<string, unknown> {
    const profile: Record<string, unknown> = {};
    profileEntries.forEach(entry => {
      const key = entry.key.trim();
      if (key) profile[key] = parseProfileValue(entry.value);
    });
    return profile;
  }

  function addProfileEntry() {
    setProfileEntries(current => [...current, { id: `entry-${Date.now()}-${current.length}`, key: '', value: '' }]);
  }

  function updateProfileEntry(id: string, field: 'key' | 'value', value: string) {
    setProfileEntries(current => current.map(entry => (entry.id === id ? { ...entry, [field]: value } : entry)));
  }

  function removeProfileEntry(id: string) {
    setProfileEntries(current => current.filter(entry => entry.id !== id));
  }

  function startEditingGroupName(group: Group) {
    setEditingGroupName(group.group_id);
    setGroupNameDraft(group.group_name || '');
  }

  async function saveGroupName(groupId: string) {
    const groupName = groupNameDraft.trim();
    if (!groupName) return;
    setError('');
    const result = await apiPost<GroupNameSettings>(`/api/groups/${groupId}/settings/name`, { group_name: groupName });
    setGroups(currentGroups => currentGroups.map(group => (group.group_id === groupId ? { ...group, group_name: result.group_name } : group)));
    setEditingGroupName('');
    setGroupNameDraft('');
    setMessage('群名称已保存');
  }

  function clearUnlockedGroup(groupId: string) {
    setGroupPasswords(current => {
      const next = { ...current };
      delete next[groupId];
      return next;
    });
    setUsers([]);
    setSelectedUser('');
    setDetail(null);
    setProfileEntries([]);
    setAccessPassword('');
  }

  async function loadUsers(groupId: string) {
    setSelectedGroup(groupId);
    setSelectedUser('');
    setDetail(null);
    setProfileEntries([]);
    setGroupPassword('');
    setAccessPassword('');
    const group = groups.find(item => item.group_id === groupId);
    if (group?.memory_password_enabled && !groupPasswords[groupId]) {
      setUsers([]);
      return;
    }
    setUsers(await apiGet<User[]>(`/api/groups/${groupId}/users`, groupPasswordHeader(groupId)));
  }

  async function unlockGroupAccess() {
    const password = accessPassword.trim();
    if (!selectedGroup || !password) return;
    try {
      const loadedUsers = await apiGet<User[]>(`/api/groups/${selectedGroup}/users`, { 'X-Group-Password': password });
      setGroupPasswords(current => ({ ...current, [selectedGroup]: password }));
      setUsers(loadedUsers);
      setAccessPassword('');
      setError('');
    } catch {
      setUsers([]);
      setError('群组密码错误或未输入');
    }
  }

  async function loadDetail(userId: string) {
    const data = await apiGet<UserDetail>(`/api/groups/${selectedGroup}/users/${userId}`, groupPasswordHeader(selectedGroup));
    setSelectedUser(userId);
    setDetail(data);
    setProfileEntries(profileRecordToEntries(data.personality_profile || {}));
    setFavorDraft(String(data.favorability ?? 0));
    setFavorDelta('');
    setMessage('');
  }

  async function saveProfile() {
    if (!selectedGroup || !selectedUser) return;
    const profile = profileEntriesToRecord();
    setError('');
    const data = await apiPost<UserDetail>(`/api/groups/${selectedGroup}/users/${selectedUser}/profile`, { profile, password: groupPasswords[selectedGroup] || '' });
    setDetail(data);
    setProfileEntries(profileRecordToEntries(data.personality_profile || {}));
    setMessage('档案已保存');
  }

  function applyDetailUpdate(data: UserDetail) {
    setDetail(data);
    setProfileEntries(profileRecordToEntries(data.personality_profile || {}));
    setFavorDraft(String(data.favorability ?? 0));
    setFavorDelta('');
    setUsers(current => current.map(item => (
      item.user_id === data.user_id
        ? { ...item, favorability: data.favorability ?? 0, level: data.level || item.level }
        : item
    )));
  }

  async function saveFavorValue() {
    if (!selectedGroup || !selectedUser) return;
    const trimmed = favorDraft.trim();
    if (!trimmed) {
      setError('请输入信任度数值');
      return;
    }
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed) || !Number.isInteger(parsed)) {
      setError('信任度必须是整数');
      return;
    }
    setError('');
    setSavingFavor(true);
    try {
      const data = await apiPost<UserDetail>(
        `/api/groups/${selectedGroup}/users/${selectedUser}/favor`,
        { favor: parsed, nickname: detail?.current_nickname || '', password: groupPasswords[selectedGroup] || '' }
      );
      applyDetailUpdate(data);
      setMessage(`信任度已设为 ${data.favorability}`);
    } catch (err) {
      setError(String(err));
    } finally {
      setSavingFavor(false);
    }
  }

  async function applyFavorDelta(direction: 1 | -1) {
    if (!selectedGroup || !selectedUser) return;
    const trimmed = favorDelta.trim();
    if (!trimmed) {
      setError('请输入增减值');
      return;
    }
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed <= 0) {
      setError('增减值必须是正整数');
      return;
    }
    setError('');
    setSavingFavor(true);
    try {
      const data = await apiPost<UserDetail>(
        `/api/groups/${selectedGroup}/users/${selectedUser}/favor`,
        { delta: parsed * direction, nickname: detail?.current_nickname || '', password: groupPasswords[selectedGroup] || '' }
      );
      applyDetailUpdate(data);
      setMessage(`信任度已 ${direction > 0 ? '+' : '-'}${parsed}（当前 ${data.favorability}）`);
    } catch (err) {
      setError(String(err));
    } finally {
      setSavingFavor(false);
    }
  }

  async function saveGroupPassword() {
    if (!selectedGroup || !groupPassword.trim()) return;
    setError('');
    const result = await apiPost<GroupSettings>(`/api/groups/${selectedGroup}/settings/password`, { password: groupPassword });
    updateGroupPasswordStatus(selectedGroup, result.memory_password_enabled);
    clearUnlockedGroup(selectedGroup);
    setGroupPassword('');
    setMessage('群组访问密码已保存，当前群组档案已锁定');
  }

  async function clearGroupPassword() {
    if (!selectedGroup || !groupPassword.trim()) return;
    setError('');
    const result = await apiDelete<GroupSettings>(`/api/groups/${selectedGroup}/settings/password`, { password: groupPassword });
    updateGroupPasswordStatus(selectedGroup, result.memory_password_enabled);
    setGroupPasswords(current => {
      const next = { ...current };
      delete next[selectedGroup];
      return next;
    });
    setGroupPassword('');
    setMessage('群组访问密码已清除');
  }

  async function deleteProfile() {
    if (!selectedGroup || !selectedUser) return;
    const response = await fetch(`/api/groups/${selectedGroup}/users/${selectedUser}/profile`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ password: groupPasswords[selectedGroup] || '' })
    });
    if (!response.ok) {
      setError(`删除失败：${response.status}`);
      setPendingDelete(false);
      return;
    }
    const body = await response.json();
    if (!body.ok) {
      setError(body.error?.message || '删除失败');
      setPendingDelete(false);
      return;
    }
    const data = body.data as UserDetail;
    setDetail(data);
    setProfileEntries(profileRecordToEntries(data.personality_profile || {}));
    setPendingDelete(false);
    setMessage('档案已清空');
  }

  return (
    <div className="three-column">
      <section className="panel page-panel">
        <h2>群聊列表</h2>
        {error && <p className="error-text">{error}</p>}
        {groups.map(group => (
          <div key={group.group_id} className={`group-row ${selectedGroup === group.group_id ? 'selected-row' : ''}`}>
            {editingGroupName === group.group_id ? (
              <>
                <input className="group-name-input" value={groupNameDraft} onChange={event => setGroupNameDraft(event.target.value)} placeholder="输入群名称" />
                <div className="group-row-actions">
                  <button disabled={!groupNameDraft.trim()} onClick={() => saveGroupName(group.group_id)}>保存名称</button>
                  <button onClick={() => setEditingGroupName('')}>取消</button>
                </div>
              </>
            ) : (
              <>
                <button onClick={() => loadUsers(group.group_id)} className="group-main-button">
                  <span>{groupLabel(group)}{group.memory_password_enabled ? ' · 记忆已加密' : ''}</span>
                  <small>{group.user_count} 名用户 · {group.message_count} 条消息</small>
                </button>
                <div className="group-row-actions">
                  <button onClick={() => startEditingGroupName(group)}>编辑名称</button>
                </div>
              </>
            )}
          </div>
        ))}
      </section>
      <section className="panel page-panel">
        <h2>用户列表</h2>
        {selectedGroupNeedsPassword && !selectedGroupPassword && (
          <div className="toolbar vertical-toolbar">
            <input type="password" value={accessPassword} onChange={event => setAccessPassword(event.target.value)} placeholder={`输入 ${groupLabel(selectedGroupRecord)} 的访问密码`} />
            <button disabled={!accessPassword.trim()} onClick={unlockGroupAccess}>解锁群组档案</button>
          </div>
        )}
        {canAccessSelectedGroup && users.map(user => (
          <button key={user.user_id} onClick={() => loadDetail(user.user_id)} className={selectedUser === user.user_id ? 'selected-row' : ''}>
            <span>{user.nickname || user.user_id}</span>
            <small>{user.level || '暂无定位'} · 好感度 {user.favorability} · {user.message_count} 条消息</small>
          </button>
        ))}
      </section>
      <section className="panel page-panel profile-editor">
        <h2>用户档案</h2>
        {message && <p className="status-ok">{message}</p>}
        {selectedGroup && (
          <div className="config-row">
            <div>
              <strong>群组访问密码</strong>
              <small>状态：{selectedGroupRecord?.memory_password_enabled ? '已启用' : '未启用'}</small>
            </div>
            <input type="password" value={groupPassword} onChange={event => setGroupPassword(event.target.value)} placeholder={selectedGroupRecord?.memory_password_enabled ? '输入当前密码或设置新密码' : '设置新的群组访问密码'} />
            <div className="group-password-actions">
              <button disabled={!groupPassword.trim()} onClick={saveGroupPassword}>设置/更新访问密码</button>
              <button disabled={!selectedGroupRecord?.memory_password_enabled || !groupPassword.trim()} onClick={clearGroupPassword}>确认当前访问密码后清除</button>
            </div>
          </div>
        )}
        {detail ? (
          <>
            <div className="profile-summary">
              <strong>{detail.current_nickname || detail.user_id}</strong>
              <small>号码：{detail.user_id}</small>
              <small>定位：{detail.level || '暂无'}</small>
              <small>信任度：{detail.favorability}</small>
              <small>发言总数：{detail.message_count} 条</small>
            </div>
            <div className="favor-editor">
              <strong>信任度调整</strong>
              <div className="favor-editor-row">
                <label>
                  直接设为
                  <input
                    type="number"
                    value={favorDraft}
                    onChange={event => setFavorDraft(event.target.value)}
                    placeholder="例如 100 / -20"
                  />
                </label>
                <button disabled={savingFavor} onClick={saveFavorValue}>保存数值</button>
              </div>
              <div className="favor-editor-row">
                <label>
                  增减
                  <input
                    type="number"
                    min={1}
                    value={favorDelta}
                    onChange={event => setFavorDelta(event.target.value)}
                    placeholder="正整数，例如 30"
                  />
                </label>
                <button disabled={savingFavor} onClick={() => applyFavorDelta(1)}>+ 加分</button>
                <button disabled={savingFavor} onClick={() => applyFavorDelta(-1)}>- 减分</button>
              </div>
              <small className="muted">阶梯：&lt;-50 看台内鬼 / &lt;0 预备队 / &lt;50 青训生 / &lt;200 一线队 / &lt;500 核心首发 / ≥500 传奇队长</small>
            </div>
            <div className="profile-entry-list">
              <div className="toolbar">
                <button onClick={addProfileEntry}>添加条目</button>
                <button onClick={saveProfile}>保存档案</button>
                <button onClick={() => setPendingDelete(true)}>清空档案</button>
              </div>
              {profileEntries.length === 0 ? <p className="muted">暂无档案条目</p> : profileEntries.map(entry => (
                <div key={entry.id} className="profile-entry-row">
                  <input value={entry.key} onChange={event => updateProfileEntry(entry.id, 'key', event.target.value)} placeholder="条目名称" />
                  <textarea value={entry.value} onChange={event => updateProfileEntry(entry.id, 'value', event.target.value)} placeholder="条目内容" rows={3} />
                  <button onClick={() => removeProfileEntry(entry.id)}>删除条目</button>
                </div>
              ))}
            </div>
            <h3>历史昵称</h3>
            <pre>{JSON.stringify(detail.nicknames, null, 2)}</pre>
            <h3>最近发言</h3>
            <pre>{JSON.stringify(detail.recent_messages.slice(0, 5), null, 2)}</pre>
          </>
        ) : (
          <p className="muted">请选择一个用户</p>
        )}
      </section>
      {pendingDelete && (
        <ConfirmDialog title="清空用户档案" message="确定清空这名用户的个人档案 JSON 吗？基础好感度和发言记录不会删除。" onCancel={() => setPendingDelete(false)} onConfirm={deleteProfile} />
      )}
    </div>
  );
}
