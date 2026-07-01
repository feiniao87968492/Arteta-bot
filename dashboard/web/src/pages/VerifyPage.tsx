import { useEffect, useState } from 'react';
import { apiGet, apiPost, getToken } from '../api/client';

const suites = ['core', 'render', 'memory', 'chat', 'commands', 'online', 'all'];

const suiteLabels: Record<string, string> = {
  core: '核心',
  render: '渲染',
  memory: '记忆',
  chat: '对话',
  commands: '指令',
  online: '在线',
  all: '全部'
};

type VerifyStart = { run_id: string };
type Report = Record<string, unknown> | null;

export function VerifyPage() {
  const [selectedSuites, setSelectedSuites] = useState<Set<string>>(new Set(['core']));
  const [caseName, setCaseName] = useState('');
  const [online, setOnline] = useState(false);
  const [allowSideEffects, setAllowSideEffects] = useState(false);
  const [lines, setLines] = useState<string[]>([]);
  const [report, setReport] = useState<Report>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => { void loadReport(); }, []);

  async function loadReport() {
    setReport(await apiGet<Report>('/api/verify/latest-report'));
  }

  function toggleSuite(name: string) {
    const next = new Set(selectedSuites);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setSelectedSuites(next);
  }

  async function start() {
    setRunning(true);
    setLines([]);
    const payload = {
      suites: Array.from(selectedSuites),
      cases: caseName.trim() ? [caseName.trim()] : [],
      online,
      allow_side_effects: allowSideEffects
    };
    try {
      const data = await apiPost<VerifyStart>('/api/verify/runs', payload);
      await streamRun(data.run_id);
      await loadReport();
    } finally {
      setRunning(false);
    }
  }

  async function streamRun(runId: string) {
    const response = await fetch(`/api/verify/runs/${runId}/events`, {
      headers: { Authorization: `Bearer ${getToken()}` }
    });
    if (!response.body) {
      setLines(current => [...current, '[dashboard] 输出流不可用']);
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';
      for (const event of events) {
        const line = event.replace(/^data: /, '').trim();
        if (line) setLines(current => [...current, line]);
      }
    }
  }

  return (
    <div className="stack">
      <section className="panel page-panel">
        <h2>功能验证中心</h2>
        <div className="checks">
          {suites.map(name => (
            <label key={name}><input type="checkbox" checked={selectedSuites.has(name)} onChange={() => toggleSuite(name)} /> {suiteLabels[name]}</label>
          ))}
        </div>
        <div className="toolbar">
          <input value={caseName} onChange={event => setCaseName(event.target.value)} placeholder="可选 case 名称" />
          <label><input type="checkbox" checked={online} onChange={event => setOnline(event.target.checked)} /> 在线检查</label>
          <label><input type="checkbox" checked={allowSideEffects} onChange={event => setAllowSideEffects(event.target.checked)} /> 允许副作用</label>
          <button disabled={running} onClick={start}>{running ? '运行中' : '开始验证'}</button>
        </div>
      </section>
      <section className="panel page-panel console"><pre>{lines.join('\n') || '暂无运行任务'}</pre></section>
      <section className="panel page-panel"><h2>最新报告</h2><pre>{report ? JSON.stringify(report, null, 2) : '未找到报告'}</pre></section>
    </div>
  );
}
