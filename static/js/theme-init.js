(function () {
  'use strict';
  try {
    var stored = localStorage.getItem('cloth_theme');
    if (stored === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
    } else if (!stored && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      // No explicit preference — auto-apply OS dark mode (WN-154)
      document.documentElement.setAttribute('data-theme', 'dark');
    }
  } catch (e) { /* localStorage unavailable */ }
}());
