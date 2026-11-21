import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { App } from './App';

test('starts asleep with a button to wake Pebbo', () => {
  render(<App />);

  expect(screen.getByRole('button', { name: 'Pebbo aufwecken' })).toBeDefined();
  expect(screen.getByRole('status').textContent).toContain('Pebbo schläft');
  expect(screen.getByRole('img', { name: 'Pebbo: sleeping' })).toBeDefined();
});
