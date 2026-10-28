import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { createLink, getLinkStats } from '../api/client';
import { Brand } from '../components/Brand';
import { StatCard } from '../components/StatCard';
import type { CreatedLink, LinkStats } from '../types/links';

function formatDate(value: string | null): string {
  if (!value) return 'Never';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Not available';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function validateUrl(value: string): string | null {
  try {
    const parsed = new URL(value.trim());
    if (!['http:', 'https:'].includes(parsed.protocol)) return 'Use an HTTP or HTTPS link.';
    if (!parsed.hostname || parsed.username || parsed.password) return 'Enter a valid URL without embedded credentials.';
    return null;
  } catch {
    return 'Enter a complete URL, including https://';
  }
}

export function HomePage() {
  const [url, setUrl] = useState('');
  const [expiresAt, setExpiresAt] = useState('');
  const [createdLink, setCreatedLink] = useState<CreatedLink | null>(null);
  const [stats, setStats] = useState<LinkStats | null>(null);
  const [statsState, setStatsState] = useState<'idle' | 'loading' | 'loaded' | 'error'>('idle');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');

  useEffect(() => {
    if (!createdLink) return;
    let cancelled = false;
    setStatsState('loading');
    getLinkStats(createdLink.code).then((value) => {
      if (!cancelled) {
        setStats(value);
        setStatsState('loaded');
      }
    }).catch(() => {
      // Link creation is successful even if the stats request temporarily fails.
      if (!cancelled) {
        setStats(null);
        setStatsState('error');
      }
    });
    return () => { cancelled = true; };
  }, [createdLink]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setCopyState('idle');
    const trimmedUrl = url.trim();
    const validationMessage = validateUrl(trimmedUrl);
    if (validationMessage) {
      setError(validationMessage);
      return;
    }

    let expiryIso: string | null = null;
    if (expiresAt) {
      const date = new Date(expiresAt);
      if (Number.isNaN(date.getTime()) || date <= new Date()) {
        setError('Choose an expiration time in the future.');
        return;
      }
      expiryIso = date.toISOString();
    }

    setIsSubmitting(true);
    try {
      const link = await createLink({ url: trimmedUrl, expires_at: expiryIso });
      setCreatedLink(link);
      setStats(null);
      setStatsState('loading');
      setUrl('');
      setExpiresAt('');
      setNotice('Your short link is ready to share.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create your short link. Try again.');
    } finally {
      setIsSubmitting(false);
    }
  }

  async function copyLink() {
    if (!createdLink) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard permission unavailable');
      await navigator.clipboard.writeText(createdLink.short_url);
      setCopyState('copied');
      setError(null);
    } catch {
      setCopyState('failed');
    }
  }

  async function refreshStats() {
    if (!createdLink) return;
    setIsRefreshing(true);
    setError(null);
    try {
      const result = await getLinkStats(createdLink.code);
      setStats(result);
      setStatsState('loaded');
    } catch (cause) {
      setStatsState('error');
      setError(cause instanceof Error ? cause.message : 'Could not refresh analytics.');
    } finally {
      setIsRefreshing(false);
    }
  }

  return (
    <div className="app-shell">
      <div className="background-orb background-orb--one" aria-hidden="true" />
      <div className="background-orb background-orb--two" aria-hidden="true" />
      <header className="site-header page-width">
        <Brand />
        <div className="header-status"><span className="status-dot" /> Clean links. Clear insights.</div>
      </header>

      <main className="page-width main-content">
        <section className="hero-copy">
          <div className="eyebrow"><span className="eyebrow-line" /> THE LINK, REIMAGINED</div>
          <h1>Long links.<br /><em>Short story.</em></h1>
          <p className="hero-subtitle">Make every character count. Create clean, shareable links and see how they perform, all in one simple place.</p>
          <div className="feature-list">
            <div><span className="feature-check">✓</span> Short, memorable URLs</div>
            <div><span className="feature-check">✓</span> Click insights, without the clutter</div>
            <div><span className="feature-check">✓</span> Optional link expiration</div>
          </div>
          <div className="decorative-stroke" aria-hidden="true"><span /><span /><span /></div>
        </section>

        <section className="workspace" aria-label="Create a short link">
          <div className="form-card">
            <div className="card-heading-row">
              <div>
                <span className="step-label">01 / CREATE</span>
                <h2>Make it shorter</h2>
                <p>Paste your destination URL below.</p>
              </div>
              <div className="link-symbol" aria-hidden="true"><LinkIcon /></div>
            </div>
            <form onSubmit={handleSubmit} noValidate>
              <label htmlFor="destination-url">Destination URL</label>
              <div className="url-input-wrap">
                <LinkIcon />
                <input
                  id="destination-url"
                  type="url"
                  autoComplete="url"
                  placeholder="https://your-long-link.com/page"
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  aria-describedby="url-help"
                  disabled={isSubmitting}
                  required
                />
              </div>
              <p className="field-help" id="url-help">Works with public HTTP and HTTPS links.</p>
              <details className="expiry-details">
                <summary><span className="plus-icon">+</span> Add an expiration date <span className="optional-label">OPTIONAL</span></summary>
                <div className="expiry-field">
                  <label htmlFor="expires-at">Link expires at</label>
                  <input id="expires-at" type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} disabled={isSubmitting} />
                  <p className="field-help">Choose a future date and time in your local timezone.</p>
                </div>
              </details>
              <button className="primary-button" type="submit" disabled={isSubmitting || !url.trim()}>
                {isSubmitting ? <><span className="spinner" /> Creating your link…</> : <>Create short link <span aria-hidden="true">↗</span></>}
              </button>
            </form>
            <p className="privacy-note"><ShieldIcon /> Your destination is validated before a link is created.</p>
          </div>

          {error && <div className="feedback feedback--error" role="alert"><span aria-hidden="true">!</span><p>{error}</p><button type="button" aria-label="Dismiss error" onClick={() => setError(null)}>×</button></div>}
          {notice && <div className="feedback feedback--success" role="status"><span aria-hidden="true">✓</span><p>{notice}</p><button type="button" aria-label="Dismiss message" onClick={() => setNotice(null)}>×</button></div>}

          {createdLink && (
            <section className="result-card" aria-label="Generated short link">
              <div className="result-topline"><span className="step-label">02 / YOUR LINK</span><span className="live-pill"><span /> READY</span></div>
              <h2>Ready for the world.</h2>
              <div className="generated-url">
                <a href={createdLink.short_url} target="_blank" rel="noreferrer">{createdLink.short_url}</a>
                <button type="button" onClick={copyLink} className="copy-button" aria-label="Copy short link"><CopyIcon /></button>
              </div>
              {copyState === 'copied' && <p className="copy-feedback" role="status">Copied to clipboard.</p>}
              {copyState === 'failed' && <p className="copy-feedback copy-feedback--error" role="status">Clipboard access was blocked. Select the URL above to copy it manually.</p>}
              <div className="original-url-line"><span>DESTINATION</span><a href={createdLink.original_url} target="_blank" rel="noreferrer">{createdLink.original_url}</a></div>
              <div className="stats-grid">
                <StatCard label="Total clicks" value={stats ? stats.total_clicks.toLocaleString() : statsState === 'error' ? 'Unavailable' : '—'} note={stats ? 'All recorded time' : statsState === 'error' ? 'Could not load analytics' : 'Analytics loading'} icon="clicks" />
                <StatCard label="Last 24 hours" value={stats ? stats.clicks_last_24_hours.toLocaleString() : statsState === 'error' ? 'Unavailable' : '—'} note={stats ? 'Recent activity' : statsState === 'error' ? 'Could not load analytics' : 'Analytics loading'} icon="recent" />
              </div>
              <div className="date-row"><div><span>CREATED</span><strong>{formatDate(createdLink.created_at)}</strong></div><div><span>EXPIRES</span><strong>{formatDate(createdLink.expires_at)}</strong></div></div>
              <button type="button" className="refresh-button" onClick={refreshStats} disabled={isRefreshing}>
                <RefreshIcon /> {isRefreshing ? 'Refreshing…' : 'Refresh analytics'}
              </button>
              <p className="analytics-note">Click events are processed asynchronously, so fresh activity may take a moment to appear.</p>
            </section>
          )}
        </section>
      </main>

      <footer className="site-footer page-width">
        <span>© {new Date().getFullYear()} ShortLink</span>
        <span className="footer-separator" aria-hidden="true">·</span>
        <span>Less link. More signal.</span>
        <span className="footer-right">Made for the things worth sharing <span aria-hidden="true">↗</span></span>
      </footer>
    </div>
  );
}

function LinkIcon() {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9.8 14.2 14.2 9.8M8 16H6.5a4.5 4.5 0 0 1 0-9H10m4 0h3.5a4.5 4.5 0 0 1 0 9H14" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
function CopyIcon() {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="8" y="8" width="11" height="12" rx="2" stroke="currentColor" strokeWidth="1.6"/><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v10A1.5 1.5 0 0 0 5.5 17H8" stroke="currentColor" strokeWidth="1.6" /></svg>;
}
function ShieldIcon() {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3.5 19 6v5.3c0 4.5-3 7.7-7 9.2-4-1.5-7-4.7-7-9.2V6l7-2.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/><path d="m9 11.7 2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
function RefreshIcon() {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/><path d="M6 9a6.5 6.5 0 0 1 11-2l3 5M4 12l3 5a6.5 6.5 0 0 0 11-2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
