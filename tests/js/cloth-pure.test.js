'use strict';
// Unit tests for cloth-pure.js pure utility functions.
// Run with: npx jest (requires Node.js 18+ and `npm install` in cloth/)

const { escapeHtml, buildCacheAgeText, deriveSimilarQuery } = require('../../static/js/cloth-pure.js');

// ------------------------------------------------------------------ //
// escapeHtml                                                           //
// ------------------------------------------------------------------ //

describe('escapeHtml', () => {
  test('leaves plain text unchanged', () => {
    expect(escapeHtml('hello world')).toBe('hello world');
  });

  test('escapes ampersand', () => {
    expect(escapeHtml('M&S')).toBe('M&amp;S');
  });

  test('escapes less-than sign', () => {
    expect(escapeHtml('<script>')).toBe('&lt;script&gt;');
  });

  test('escapes double quote', () => {
    expect(escapeHtml('"quoted"')).toBe('&quot;quoted&quot;');
  });

  test('escapes single quote', () => {
    expect(escapeHtml("it's fine")).toBe('it&#39;s fine');
  });

  test('escapes all special characters together', () => {
    expect(escapeHtml('<a href="x" title=\'y\'>&amp;</a>'))
      .toBe('&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;amp;&lt;/a&gt;');
  });

  test('coerces non-string input to string', () => {
    expect(escapeHtml(42)).toBe('42');
    expect(escapeHtml(null)).toBe('null');
  });

  test('handles empty string', () => {
    expect(escapeHtml('')).toBe('');
  });
});

// ------------------------------------------------------------------ //
// buildCacheAgeText                                                    //
// ------------------------------------------------------------------ //

describe('buildCacheAgeText', () => {
  test('returns empty string for null', () => {
    expect(buildCacheAgeText(null)).toBe('');
  });

  test('returns empty string for undefined', () => {
    expect(buildCacheAgeText(undefined)).toBe('');
  });

  test('returns just-fetched text for 0 minutes', () => {
    expect(buildCacheAgeText(0)).toContain('Just fetched');
  });

  test('returns singular minute text for 1 minute', () => {
    const result = buildCacheAgeText(1);
    expect(result).toContain('1 minute');
    expect(result).not.toContain('minutes');
  });

  test('returns plural minutes text for 30 minutes', () => {
    expect(buildCacheAgeText(30)).toContain('30 minutes');
  });

  test('returns hours text for 60 minutes', () => {
    expect(buildCacheAgeText(60)).toContain('1 hour');
    expect(buildCacheAgeText(60)).not.toContain('hours');
  });

  test('returns plural hours text for 120 minutes', () => {
    expect(buildCacheAgeText(120)).toContain('2 hours');
  });

  test('truncates partial hours correctly (90 minutes = 1 hour)', () => {
    expect(buildCacheAgeText(90)).toContain('1 hour');
  });
});

// ------------------------------------------------------------------ //
// deriveSimilarQuery                                                   //
// ------------------------------------------------------------------ //

describe('deriveSimilarQuery', () => {
  test('strips pound price from name', () => {
    const result = deriveSimilarQuery('Blue Shirt £29.99');
    expect(result).not.toContain('£');
    expect(result).not.toContain('29.99');
  });

  test('strips dollar price from name', () => {
    const result = deriveSimilarQuery('Red Dress $45.00');
    expect(result).not.toContain('$');
  });

  test('strips UK size token', () => {
    const result = deriveSimilarQuery('Navy Chinos UK 32');
    expect(result).not.toMatch(/\buk\b/i);
    expect(result).not.toContain('32');
  });

  test('strips alphabetic size tokens (XL)', () => {
    const result = deriveSimilarQuery('Wool Coat XL Black');
    expect(result).not.toMatch(/\bxl\b/i);
  });

  test('strips parenthetical notes', () => {
    const result = deriveSimilarQuery('Linen Trousers (Pack of 2)');
    expect(result).not.toContain('Pack');
  });

  test('limits output to five words', () => {
    const result = deriveSimilarQuery('one two three four five six seven eight');
    expect(result.split(' ').length).toBeLessThanOrEqual(5);
  });

  test('collapses extra whitespace', () => {
    const result = deriveSimilarQuery('Blue   Linen   Shirt');
    expect(result).not.toContain('  ');
  });

  test('handles name with no special tokens', () => {
    const result = deriveSimilarQuery('Navy Chinos');
    expect(result).toBe('Navy Chinos');
  });
});
