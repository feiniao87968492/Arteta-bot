import { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';

type ProviderField = {
  name: string;
  label: string;
  secret: boolean;
  configured: boolean;
  value: string;
};

type Provider = {
  id: string;
  label: string;
  configured: boolean;
  fields: ProviderField[];
};

type Validation = {
  provider: string;
  receipt: string;
  expires_in: number;
};

type ApplyResult = {
  provider: string;
  active: boolean;
  persistence_succeeded: boolean;
  initial_restart_failed: boolean;
  rolled_back: boolean;
  recovery_active: boolean;
  recovery_restart_succeeded: boolean;
  restart_error: string;
};

export function ConfigPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const [validation, setValidation] = useState<Record<string, Validation | null>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [pendingApply, setPendingApply] = useState<Provider | null>(null);
  const [message, setMessage] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => { void load(); }, []);

  async function load() {
    const result = await apiGet<Provider[]>('/api/config/providers');
    setProviders(result);
  }

  function candidate(provider: Provider): Record<string, string> {
    const draft = drafts[provider.id] || {};
    return Object.fromEntries(provider.fields.map(field => [
      field.name,
      draft[field.name] ?? (field.secret ? '' : field.value),
    ]));
  }

  function setField(provider: Provider, field: ProviderField, value: string) {
    setDrafts(current => ({
      ...current,
      [provider.id]: { ...(current[provider.id] || {}), [field.name]: value },
    }));
    setValidation(current => ({ ...current, [provider.id]: null }));
    setErrors(current => ({ ...current, [provider.id]: '' }));
  }

  function hasCompleteCandidate(provider: Provider): boolean {
    return Object.values(candidate(provider)).every(value => value.trim().length > 0);
  }

  async function verify(provider: Provider) {
    setBusy(`verify:${provider.id}`);
    setErrors(current => ({ ...current, [provider.id]: '' }));
    try {
      const result = await apiPost<Validation>(
        `/api/config/providers/${encodeURIComponent(provider.id)}/validate`,
        { values: candidate(provider) },
      );
      setValidation(current => ({ ...current, [provider.id]: result }));
      setMessage(`${provider.label} configuration verified`);
    } catch (error) {
      setValidation(current => ({ ...current, [provider.id]: null }));
      setErrors(current => ({ ...current, [provider.id]: error instanceof Error ? error.message : 'Verification failed' }));
    } finally {
      setBusy(null);
    }
  }

  async function apply(provider: Provider) {
    const receipt = validation[provider.id]?.receipt;
    if (!receipt) return;
    setBusy(`apply:${provider.id}`);
    setErrors(current => ({ ...current, [provider.id]: '' }));
    try {
      const result = await apiPost<ApplyResult>(
        `/api/config/providers/${encodeURIComponent(provider.id)}/apply`,
        { values: candidate(provider), receipt },
      );
      setValidation(current => ({ ...current, [provider.id]: null }));
      if (!result.active) {
        const recovery = result.recovery_active ? 'Previous configuration was restored.' : 'Recovery restart failed.';
        setErrors(current => ({ ...current, [provider.id]: `${result.restart_error || 'Bot restart failed'}. ${recovery}` }));
        return;
      }
      setDrafts(current => {
        const next = { ...current };
        delete next[provider.id];
        return next;
      });
      setMessage(`${provider.label} applied and bot restarted`);
      await load();
    } catch (error) {
      setValidation(current => ({ ...current, [provider.id]: null }));
      setErrors(current => ({ ...current, [provider.id]: error instanceof Error ? error.message : 'Apply failed' }));
    } finally {
      setBusy(null);
      setPendingApply(null);
    }
  }

  return (
    <div className="stack">
      <section className="panel page-panel config-page">
        <div className="config-heading">
          <div>
            <p className="eyebrow">PROVIDER CONTROL</p>
            <h2>服务配置</h2>
          </div>
          <p className="muted">每组独立验证后才能应用。应用会立即重启机器人。</p>
        </div>
        {message && <p className="status-ok config-message">{message}</p>}
        <div className="provider-grid">
          {providers.map(provider => {
            const verified = validation[provider.id];
            const complete = hasCompleteCandidate(provider);
            const verifying = busy === `verify:${provider.id}`;
            const applying = busy === `apply:${provider.id}`;
            return (
              <section className="provider-card" key={provider.id}>
                <header className="provider-card-header">
                  <div>
                    <h3>{provider.label}</h3>
                    <small className={provider.configured ? 'status-ok' : 'status-warn'}>
                      {provider.configured ? 'Configured' : 'Incomplete'}
                    </small>
                  </div>
                  {verified && <span className="provider-verified">Verified</span>}
                </header>
                <div className="provider-fields">
                  {provider.fields.map(field => (
                    <label key={field.name}>
                      <span>{field.label}</span>
                      <small>{field.name}</small>
                      <input
                        type={field.secret ? 'password' : 'text'}
                        autoComplete={field.secret ? 'new-password' : 'off'}
                        value={candidate(provider)[field.name]}
                        placeholder={field.secret && field.configured ? 'Re-enter API key to update' : field.secret ? 'API key' : field.label}
                        onChange={event => setField(provider, field, event.target.value)}
                      />
                    </label>
                  ))}
                </div>
                <div className="provider-actions">
                  <button disabled={!complete || busy !== null} onClick={() => { void verify(provider); }}>
                    {verifying ? 'Verifying...' : 'Verify configuration'}
                  </button>
                  <button disabled={!verified || busy !== null} onClick={() => setPendingApply(provider)}>
                    {applying ? 'Applying...' : 'Apply and restart bot'}
                  </button>
                </div>
                {verified && <small className="provider-note">Verification expires in {verified.expires_in}s and is invalidated by edits.</small>}
                {errors[provider.id] && <small className="status-error provider-note">{errors[provider.id]}</small>}
              </section>
            );
          })}
        </div>
      </section>
      {pendingApply && (
        <ConfirmDialog
          title="Apply provider configuration"
          message={`Apply the verified ${pendingApply.label} configuration and restart arteta_bot?`}
          onCancel={() => setPendingApply(null)}
          onConfirm={() => { void apply(pendingApply); }}
        />
      )}
    </div>
  );
}
