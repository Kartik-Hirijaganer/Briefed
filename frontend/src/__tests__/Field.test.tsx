import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Field } from '@briefed/ui';

describe('<Field>', () => {
  it('wires `htmlFor`, `aria-describedby`, and `aria-invalid` through to the control', () => {
    render(
      <Field label="Name" description="Your full name" error="Required">
        <input name="name" />
      </Field>,
    );
    const input = screen.getByLabelText(/Name/);
    expect(input).toHaveAttribute('aria-invalid', 'true');
    const describedBy = input.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    const described = describedBy?.split(' ') ?? [];
    const texts = described.map((id) => document.getElementById(id)?.textContent);
    expect(texts).toEqual(expect.arrayContaining(['Your full name', 'Required']));
  });

  it('marks required fields with aria-required', () => {
    render(
      <Field label="Email" required>
        <input type="email" />
      </Field>,
    );
    expect(screen.getByLabelText(/Email/)).toHaveAttribute('aria-required', 'true');
  });
});
