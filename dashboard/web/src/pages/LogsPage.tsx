import { useEffect, useMemo, useState } from 'react';
import { apiGet } from '../api/client';

type LogFile = { name: string; size: number; mtime: number };
type TailResponse = { name: string; lines: string[] };

export function LogsPage() {
  const [logs, setLogs] = useState<LogFile[]>([]);
  const [selected, setSelected] = useState('arteta_bot.log');
  const [lines, setLines] = useState<string[]>([]);
  const [level, setLevel] = useState('');
  const [keyword, setKeyword] = useState('');

  useEffect(() => { void loadLogs(); }, []);

  async function loadLogs() {
    const files = await apiGet<LogFile[]>('/api/logs');
    setLogs(files);
    if (!files.length) return;
    const nextSelected = files.find(file => file.name === selected)?.name || files[0].name;
    setSelected(nextSelected);
    await tail(nextSelected);
  }

  async function tail(name = selected) {
    const data = await apiGet<TailResponse>(`/api/logs/tail?name=${encodeURIComponent(name)}&limit=300`);
    setLines(data.lines);
  }

  const filtered = useMemo(() => {
    return lines.filter(line => (!level || line.includes(level)) && (!keyword || line.toLowerCase().includes(keyword.toLowerCase())));
  }, [lines, level, keyword]);

  return (
    <div className="stack">
      <section className="panel page-panel toolbar">
        <select value={selected} onChange={event => { setSelected(event.target.value); void tail(event.target.value); }}>
          {logs.map(file => <option key={file.name} value={file.name}>{file.name}</option>)}
        </select>
        <select value={level} onChange={event => setLevel(event.target.value)}>
          <option value="">全部级别</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
          <option value="CRITICAL">CRITICAL</option>
        </select>
        <input value={keyword} onChange={event => setKeyword(event.target.value)} placeholder="关键词过滤" />
        <button onClick={() => tail()}>读取日志尾部</button>
      </section>
      <section className="panel page-panel console"><pre>{filtered.join('\n') || '暂无日志内容'}</pre></section>
    </div>
  );
}
