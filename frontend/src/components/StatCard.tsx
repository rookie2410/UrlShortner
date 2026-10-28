interface StatCardProps {
  label: string;
  value: string | number;
  note: string;
  icon: 'clicks' | 'recent';
}

export function StatCard({ label, value, note, icon }: StatCardProps) {
  return (
    <section className="stat-card" aria-label={label}>
      <div className={`stat-icon stat-icon--${icon}`} aria-hidden="true">
        {icon === 'clicks' ? <ClickIcon /> : <ClockIcon />}
      </div>
      <div className="stat-meta">
        <p>{label}</p>
        <strong>{value}</strong>
        <span>{note}</span>
      </div>
    </section>
  );
}

function ClickIcon() {
  return <svg viewBox="0 0 24 24" fill="none"><path d="M7 4v7l3-2 3 6 2-1-3-6 4-.5L7 4Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round"/><path d="m15 15 2 4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg>;
}

function ClockIcon() {
  return <svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.7"/><path d="M12 7v5l3 2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
