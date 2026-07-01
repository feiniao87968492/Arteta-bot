import type { ReactNode } from 'react';
import type { StatusCardState } from '../api/types';

type Props = {
  title: string;
  state: StatusCardState;
  value: string;
  children?: ReactNode;
};

export function StatusCard({ title, state, value, children }: Props) {
  return (
    <section className="panel status-card">
      <div className={`status-light status-${state}`} aria-hidden="true">●</div>
      <h2>{title}</h2>
      <strong>{value}</strong>
      {children && <div className="status-detail">{children}</div>}
    </section>
  );
}
