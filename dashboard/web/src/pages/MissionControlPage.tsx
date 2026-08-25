import { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { StatusCard } from '../components/StatusCard';

type PowerState = {
  enabled: boolean;
  updated_at: string;
  actor: string;
  reason: string;
};

type Overview = {
  paths: Record<string, { path: string; exists: boolean }>;
  groups: { count: number };
  chroma: { available: boolean; count: number; collection?: string };
  logs: { count: number };
  readonly: boolean;
  bot_power: PowerState;
  sync: {
    available: boolean;
    stale: boolean;
    last_success_at: string;
    last_error: string;
    remote_db: string;
    local_db: string;
    bytes: number;
    duration_ms: number;
    interval_seconds: number;
  };
};

export function MissionControlPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState('');
  const [power, setPower] = useState<PowerState | null>(null);
  const [pendingToggle, setPendingToggle] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');

  useEffect(() => {
    apiGet<Overview>('/api/overview')
      .then(data => {
        setOverview(data);
        setPower(data.bot_power);
      })
      .catch(err => setError(String(err)));
  }, []);

  const handleToggle = async () => {
    if (!power) return;
    setBusy(true);
    setFeedback('');
    try {
      const next = await apiPost<PowerState>('/api/bot-power', {
        enabled: !power.enabled,
        reason: '',
      });
      setPower(next);
      setFeedback(next.enabled ? '机器人已恢复响应' : '机器人已停止对话');
    } catch (err) {
      setFeedback('操作失败：' + String(err));
    } finally {
      setBusy(false);
      setPendingToggle(false);
    }
  };

  if (error) {
    return <div className="panel page-panel error-text">{error}</div>;
  }
  if (!overview || !power) {
    return <div className="panel page-panel">正在加载遥测数据...</div>;
  }

  const powerOn = power.enabled;
  const updatedLabel = power.updated_at ? `上次操作：${power.updated_at}` : '尚未手动切换';

  return (
    <>
      <div className="grid">
        <StatusCard
          title="机器人电源"
          state={powerOn ? 'ok' : 'error'}
          value={powerOn ? '响应中' : '已断电'}
        >
          <div>{updatedLabel}</div>
          {feedback && <div style={{ marginTop: 8 }}>{feedback}</div>}
          <button
            style={{ marginTop: 12 }}
            disabled={busy || overview.readonly}
            onClick={() => setPendingToggle(true)}
          >
            {powerOn ? '停止机器人响应' : '恢复机器人响应'}
          </button>
        </StatusCard>
        <StatusCard title="SQLite 数据库" state={overview.paths.db.exists ? 'ok' : 'error'} value={overview.paths.db.exists ? '在线' : '缺失'}>
          {overview.paths.db.path}
        </StatusCard>
        <StatusCard
          title="ECS 数据同步"
          state={overview.sync.last_error ? 'error' : overview.sync.available && !overview.sync.stale ? 'ok' : 'warn'}
          value={overview.sync.last_error ? '同步失败' : overview.sync.available && !overview.sync.stale ? '刚刚同步' : '已过期'}
        >
          {overview.sync.available ? `${overview.sync.remote_db || '未知远端'} · ${overview.sync.bytes} bytes` : '未启用 ECS 同步'}
        </StatusCard>
        <StatusCard title="Chroma 记忆库" state={overview.chroma.available ? 'ok' : 'warn'} value={`${overview.chroma.count} 条记录`}>
          {overview.chroma.collection || 'group_memories'}
        </StatusCard>
        <StatusCard title="群聊频道" state="idle" value={`${overview.groups.count} 个群`}>
          SQLite 更衣室名单聚合
        </StatusCard>
        <StatusCard title="日志文件" state={overview.logs.count ? 'ok' : 'warn'} value={`${overview.logs.count} 个文件`}>
          实时遥测来源
        </StatusCard>
        <StatusCard title="运行模式" state={overview.readonly ? 'warn' : 'ok'} value={overview.readonly ? '只读模式' : '维护就绪'}>
          破坏性操作均需要二次确认
        </StatusCard>
      </div>
      {pendingToggle && (
        <ConfirmDialog
          title={powerOn ? '确认停止机器人响应？' : '确认恢复机器人响应？'}
          message={
            powerOn
              ? '关闭后所有群里的对话指令、@回复、/算法 解题与每日/每周定时任务都会被静默跳过。工具类命令（赞我、画图等）保持可用。'
              : '恢复后机器人会立即重新响应群聊和定时任务。'
          }
          onCancel={() => setPendingToggle(false)}
          onConfirm={handleToggle}
        />
      )}
    </>
  );
}
