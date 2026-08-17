(function () {
  'use strict';
  try {
    if (localStorage.getItem('cloth_theme') === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
    }
  } catch (e) { /* localStorage unavailable */ }
}());
