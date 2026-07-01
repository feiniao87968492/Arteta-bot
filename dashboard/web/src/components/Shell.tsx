import type { ReactNode } from 'react';

type ShellProps = {
  page: string;
  onNavigate: (page: string) => void;
  children: ReactNode;
};

const pages = [
  ['overview', '任务总览'],
  ['chat', '机器人对话'],
  ['groups', '群聊档案'],
  ['memories', '记忆管理'],
  ['verify', '功能验证'],
  ['docs', '文档库'],
  ['logs', '实时日志'],
  ['prompts', 'Prompt 人设'],
  ['config', '配置密钥']
];

export function Shell({ page, onNavigate, children }: ShellProps) {
  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">ARTETA BOT / 内部遥测</div>
          <h1>arteta_bot控制面板</h1>
        </div>
        <nav aria-label="仪表盘栏目">
          {pages.map(([id, label]) => (
            <button key={id} className={page === id ? 'active' : ''} onClick={() => onNavigate(id)}>
              {label}
            </button>
          ))}
        </nav>
      </header>
      <main>{children}</main>
    </div>
  );
}
