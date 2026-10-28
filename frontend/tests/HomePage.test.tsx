import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HomePage } from '../src/pages/HomePage';
import { createLink, getLinkStats } from '../src/api/client';
import type { CreatedLink, LinkStats } from '../src/types/links';

vi.mock('../src/api/client', () => ({
  createLink: vi.fn(),
  getLinkStats: vi.fn(),
}));

const link: CreatedLink = {
  code: 'AbCdEfG',
  short_url: 'http://localhost:8000/AbCdEfG',
  original_url: 'https://example.com/path',
  created_at: '2026-10-28T12:00:00Z',
  expires_at: null,
};
const stats: LinkStats = {
  code: 'AbCdEfG', total_clicks: 7, clicks_last_24_hours: 2,
  created_at: '2026-10-28T12:00:00Z', expires_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(createLink).mockResolvedValue(link);
  vi.mocked(getLinkStats).mockResolvedValue(stats);
});

describe('HomePage', () => {
  it('shows validation feedback for an invalid URL', async () => {
    const user = userEvent.setup();
    render(<HomePage />);
    await user.type(screen.getByLabelText(/destination url/i), 'javascript:alert(1)');
    await user.click(screen.getByRole('button', { name: /create short link/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/http or https/i);
    expect(createLink).not.toHaveBeenCalled();
  });

  it('creates a short link and renders persisted analytics', async () => {
    const user = userEvent.setup();
    render(<HomePage />);
    await user.type(screen.getByLabelText(/destination url/i), 'https://example.com/path');
    await user.click(screen.getByRole('button', { name: /create short link/i }));
    expect(await screen.findByText('http://localhost:8000/AbCdEfG')).toBeInTheDocument();
    await waitFor(() => expect(getLinkStats).toHaveBeenCalledWith('AbCdEfG'));
    expect(await screen.findByText('7')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('shows API errors without claiming the link was created', async () => {
    vi.mocked(createLink).mockRejectedValue(new Error('Too many requests.'));
    const user = userEvent.setup();
    render(<HomePage />);
    await user.type(screen.getByLabelText(/destination url/i), 'https://example.com/path');
    await user.click(screen.getByRole('button', { name: /create short link/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests.');
    expect(screen.queryByLabelText('Generated short link')).not.toBeInTheDocument();
  });

  it('handles clipboard permission failures', async () => {
    vi.mocked(getLinkStats).mockResolvedValue(stats);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('blocked')) } });
    const user = userEvent.setup();
    render(<HomePage />);
    await user.type(screen.getByLabelText(/destination url/i), 'https://example.com/path');
    await user.click(screen.getByRole('button', { name: /create short link/i }));
    const copyButton = await screen.findByRole('button', { name: /copy short link/i });
    await user.click(copyButton);
    expect(await screen.findByText(/select the url above to copy it manually/i)).toBeInTheDocument();
  });
});
