import { useState } from 'react';
import { apiPost, setToken } from '../api/client';

export function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError('');
    try {
      const data = await apiPost<{ token: string }>('/api/auth/login', { password });
      setToken(data.token);
      onLogin();
    } catch (err) {
      setError(err instanceof Error ? err.message : '认证失败');
    }
  }

  return (
    <div className="login-page">
      <form className="panel login-panel" onSubmit={submit}>
        <div className="eyebrow">安全访问</div>
        <h1>阿尔特塔任务控制台</h1>
        <input
          type="password"
          value={password}
          onChange={event => setPassword(event.target.value)}
          placeholder="开发者面板管理员密码"
          autoComplete="current-password"
        />
        <button type="submit">登录</button>
        {error && <p className="error-text">{error}</p>}
      </form>
    </div>
  );
}
