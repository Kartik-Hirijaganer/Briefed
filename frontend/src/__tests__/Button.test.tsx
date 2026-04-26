import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { Button } from '@briefed/ui';

describe('<Button>', () => {
  it('renders a button element when variant is not "link"', () => {
    render(
      <Button variant="primary" onClick={() => undefined}>
        Go
      </Button>,
    );
    expect(screen.getByRole('button', { name: 'Go' })).toBeInTheDocument();
  });

  it('renders an anchor when variant is "link"', () => {
    render(
      <Button variant="link" href="https://example.com">
        Learn more
      </Button>,
    );
    const link = screen.getByRole('link', { name: 'Learn more' });
    expect(link).toHaveAttribute('href', 'https://example.com');
  });

  it('fires onClick when clicked', async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    render(
      <Button variant="primary" onClick={handler}>
        Do it
      </Button>,
    );
    await user.click(screen.getByRole('button', { name: 'Do it' }));
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('disables interaction while loading', async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    render(
      <Button variant="primary" loading onClick={handler}>
        Busy
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Busy' });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(handler).not.toHaveBeenCalled();
  });

  it('rejects invalid variant/href combinations at the type level', () => {
    // The cases below demonstrate the discriminated union via @ts-expect-error:
    // they fail to compile if the union ever loosens.
    // @ts-expect-error — link requires href
    const missingHref = <Button variant="link">x</Button>;
    const houseHasHref = (
      // @ts-expect-error — non-link variants cannot accept href
      <Button variant="primary" href="/x">
        x
      </Button>
    );
    // Reference the vars so ESLint does not flag unused locals.
    expect(missingHref).toBeDefined();
    expect(houseHasHref).toBeDefined();
  });
});
