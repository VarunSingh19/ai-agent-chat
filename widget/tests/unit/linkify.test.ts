import { describe, expect, it } from 'vitest';
import { linkify } from '../../src/components/message.ts';

describe('linkify (Rules.md §5 LLM10)', () => {
  it('links only https URLs and trims trailing punctuation', () => {
    expect(linkify('See https://example.com/rules. Thanks')).toEqual([
      'See ',
      { href: 'https://example.com/rules', label: 'https://example.com/rules' },
      '. Thanks',
    ]);
  });

  it('leaves http, javascript and data URLs as plain text', () => {
    for (const text of ['http://evil.test', 'javascript:alert(1)', 'data:text/html,<b>x</b>']) {
      expect(linkify(text)).toEqual([text]);
    }
  });

  it('keeps HTML in model output as plain text parts', () => {
    expect(linkify('<img src=x onerror=alert(1)>')).toEqual(['<img src=x onerror=alert(1)>']);
  });
});
