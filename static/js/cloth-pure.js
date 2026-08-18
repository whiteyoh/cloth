// cloth-pure.js — pure utility functions with no DOM or side-effect dependencies.
// Dual-mode: CommonJS module in Node.js (for Jest); browser global otherwise.
(function (exports) {
  'use strict';

  /**
   * Escape HTML special characters to prevent XSS in string interpolation.
   * @param {string} str
   * @returns {string}
   */
  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * Build a human-readable cache age string from a minute count.
   * @param {number|null|undefined} minutes
   * @returns {string}
   */
  function buildCacheAgeText(minutes) {
    if (minutes === null || minutes === undefined) return '';
    if (minutes === 0) return 'Fetched now · ';
    if (minutes === 1) return 'Results from 1 minute ago · ';
    if (minutes < 60) return 'Results from ' + minutes + ' minutes ago · ';
    var hours = Math.floor(minutes / 60);
    return 'Results from ' + hours + ' hour' + (hours !== 1 ? 's' : '') + ' ago · ';
  }

  /**
   * Derive a "find similar" search query from a product name by stripping price,
   * size tokens, and parenthetical notes, then taking the first five words.
   * @param {string} name
   * @returns {string}
   */
  function deriveSimilarQuery(name) {
    return name
      .replace(/[£$€]\s*[\d,.]+/g, '')
      .replace(/\b(size|uk|eu|us)\s*\d+\b/gi, '')
      .replace(/\b(xs|s|m|l|xl|xxl|xxxl|one size)\b/gi, '')
      .replace(/\(\s*[^)]*\)/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .split(/\s+/)
      .slice(0, 5)
      .join(' ');
  }

  exports.escapeHtml = escapeHtml;
  exports.buildCacheAgeText = buildCacheAgeText;
  exports.deriveSimilarQuery = deriveSimilarQuery;

})(typeof module !== 'undefined' && module.exports ? module.exports : (window.ClothPure = {}));
