import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SafeMarkdown } from '@briefed/ui';

describe('<SafeMarkdown>', () => {
  it('renders allowlisted markdown elements', () => {
    render(<SafeMarkdown>**Renewal** at $4,500/yr.</SafeMarkdown>);
    expect(screen.getByText('Renewal')).toBeInTheDocument();
  });

  it('strips raw <script> tags from the source', () => {
    render(<SafeMarkdown>{`Hello <script>window.__pwned__=true</script> world`}</SafeMarkdown>);
    expect(document.querySelector('script')).toBeNull();
    // The literal payload becomes inert text; either dropped or escaped.
    expect((window as unknown as { __pwned__?: boolean }).__pwned__).toBeUndefined();
  });

  it('strips img onerror payloads', () => {
    render(<SafeMarkdown>{`![](x" onerror="alert(1))`}</SafeMarkdown>);
    expect(document.querySelector('img[onerror]')).toBeNull();
  });

  it('does not render <iframe> tags', () => {
    render(<SafeMarkdown>{`<iframe src="https://evil.example"></iframe>`}</SafeMarkdown>);
    expect(document.querySelector('iframe')).toBeNull();
  });

  it('coerces anchor links to noopener+noreferrer', () => {
    render(<SafeMarkdown>[click](https://example.com)</SafeMarkdown>);
    const link = screen.getByRole('link', { name: 'click' });
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('drops javascript: URLs entirely', () => {
    render(<SafeMarkdown>[bad](javascript:alert(1))</SafeMarkdown>);
    const link = screen.queryByRole('link');
    if (link) {
      expect(link.getAttribute('href') ?? '').not.toContain('javascript:');
    }
  });
});
