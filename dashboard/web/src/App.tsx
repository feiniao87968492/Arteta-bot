import { useState } from 'react';
import { Shell } from './components/Shell';
import { BotChatPage } from './pages/BotChatPage';
import { ConfigPage } from './pages/ConfigPage';
import { DocsPage } from './pages/DocsPage';
import { GroupsPage } from './pages/GroupsPage';
import { LogsPage } from './pages/LogsPage';
import { MemoriesPage } from './pages/MemoriesPage';
import { MissionControlPage } from './pages/MissionControlPage';
import { PromptPage } from './pages/PromptPage';
import { VerifyPage } from './pages/VerifyPage';

export function App() {
  const [enteredDashboard, setEnteredDashboard] = useState(false);
  const [page, setPage] = useState('overview');

  if (!enteredDashboard) {
    return (
      <main className="launch-page">
        <section className="launch-panel">
          <p className="mission-kicker launch-kicker">ARTETA BOT / MATCHDAY CONTROL</p>
          <button className="launch-start-button" onClick={() => setEnteredDashboard(true)}>
            开始
          </button>
        </section>
      </main>
    );
  }

  return (
    <Shell page={page} onNavigate={setPage}>
      {page === 'overview' && <MissionControlPage />}
      {page === 'chat' && <BotChatPage onOpenVerify={() => setPage('verify')} />}
      {page === 'groups' && <GroupsPage />}
      {page === 'memories' && <MemoriesPage />}
      {page === 'verify' && <VerifyPage />}
      {page === 'docs' && <DocsPage />}
      {page === 'logs' && <LogsPage />}
      {page === 'prompts' && <PromptPage />}
      {page === 'config' && <ConfigPage />}
    </Shell>
  );
}
