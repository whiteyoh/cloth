// Cloth — minimal UI enhancements
(function () {
  'use strict';

  // Auto-focus search input on home page — only on pointer:fine devices (WN-119)
  var heroInput = document.querySelector('.hero input[name="q"]');
  if (heroInput && window.matchMedia('(pointer: fine)').matches) {
    heroInput.focus();
  }

  // Search form loading feedback (home page full-nav path; results page AJAX path handled separately)
  function initSearchLoadingFeedback() {
    document.querySelectorAll('form[action="/search"]').forEach(function (form) {
      if (form._feedbackBound) return;
      form._feedbackBound = true;
      form.addEventListener('submit', function () {
        var btn = form.querySelector('button[type="submit"]');
        if (btn) {
          btn.dataset.originalLabel = btn.textContent;
          btn.disabled = true;
          btn.textContent = 'Searching…';
          btn.classList.add('is-loading');
          setTimeout(function () {
            if (btn.classList.contains('is-loading')) btn.textContent = 'AI is expanding your search…';
          }, 4000);
          setTimeout(function () {
            if (btn.classList.contains('is-loading')) btn.textContent = 'Still searching — first searches may take a moment…';
          }, 10000);
        }
      });
    });
  }

  // Reset button state on back-navigation (pageshow fires after bfcache restore)
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) {
      document.querySelectorAll('button[type="submit"].is-loading').forEach(function (btn) {
        btn.disabled = false;
        btn.classList.remove('is-loading');
        if (btn.dataset.originalLabel) {
          btn.textContent = btn.dataset.originalLabel;
        }
      });
    }
  });

  function saveSearchToHistory(query) {
    if (!query || !query.trim()) return;
    var KEY = 'cloth_search_history';
    var history = JSON.parse(localStorage.getItem(KEY) || '[]');
    history = history.filter(function (q) { return q !== query.trim(); });
    history.unshift(query.trim());
    history = history.slice(0, 10);
    localStorage.setItem(KEY, JSON.stringify(history));
  }

  var _CURATED_SUGGESTIONS = [
    'navy chinos', 'floral midi dress', 'oversized cream jumper', 'wool coat',
    'white trainers', 'smart casual shirt', 'linen suit', 'leather boots',
    'summer wedding guest dress', 'men\'s casual trousers', 'women\'s blazer',
    'denim jacket', 'ankle boots', 'cashmere sweater', 'wrap dress'
  ];

  function initThemeToggle() {
    var btn = document.getElementById('theme-toggle');
    if (!btn || btn._themeBound) return;
    btn._themeBound = true;
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
    btn.textContent = isDark ? '☽' : '☀';

    btn.addEventListener('click', function () {
      isDark = !isDark;
      if (isDark) {
        document.documentElement.setAttribute('data-theme', 'dark');
      } else {
        document.documentElement.removeAttribute('data-theme');
      }
      btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
      btn.textContent = isDark ? '☽' : '☀';
      try {
        localStorage.setItem('cloth_theme', isDark ? 'dark' : 'light');
      } catch (e) { /* ignore */ }
    });
  }

  function initSearchAutocomplete() {
    var history = [];
    try {
      history = JSON.parse(localStorage.getItem('cloth_search_history') || '[]');
    } catch (e) { /* ignore */ }

    var combined = history.slice(0, 10).concat(
      _CURATED_SUGGESTIONS.filter(function (s) {
        return !history.includes(s);
      })
    );

    // Legacy datalist fill (fallback if JS custom listbox not supported)
    ['cloth-autocomplete-hero', 'cloth-autocomplete-header'].forEach(function (id) {
      var dl = document.getElementById(id);
      if (!dl) return;
      combined.forEach(function (term) {
        var opt = document.createElement('option');
        opt.value = term;
        dl.appendChild(opt);
      });
    });

    // WN-159: custom keyboard-navigable listbox for each search input
    document.querySelectorAll('input[list="cloth-autocomplete-hero"], input[list="cloth-autocomplete-header"]').forEach(function (input) {
      if (input._acBound) return;
      input._acBound = true;

      var listboxId = 'ac-listbox-' + Math.random().toString(36).slice(2, 7);
      var activeId = null;

      var lb = document.createElement('ul');
      lb.id = listboxId;
      lb.className = 'ac-listbox';
      lb.setAttribute('role', 'listbox');
      lb.style.display = 'none';
      input.parentNode.style.position = 'relative';
      input.parentNode.appendChild(lb);

      input.setAttribute('role', 'combobox');
      input.setAttribute('aria-autocomplete', 'list');
      input.setAttribute('aria-expanded', 'false');
      input.setAttribute('aria-owns', listboxId);
      input.setAttribute('autocomplete', 'off');

      var liveRegion = document.createElement('span');
      liveRegion.className = 'sr-only';
      liveRegion.setAttribute('aria-live', 'polite');
      liveRegion.setAttribute('aria-atomic', 'true');
      input.parentNode.appendChild(liveRegion);

      function getMatches(val) {
        if (!val) return combined.slice(0, 8);
        var lv = val.toLowerCase();
        return combined.filter(function (s) { return s.toLowerCase().indexOf(lv) !== -1; }).slice(0, 8);
      }

      function renderListbox(matches) {
        lb.innerHTML = '';
        activeId = null;
        input.removeAttribute('aria-activedescendant');
        if (!matches.length) { closeLb(); return; }
        matches.forEach(function (s, i) {
          var li = document.createElement('li');
          li.className = 'ac-option';
          li.setAttribute('role', 'option');
          li.setAttribute('id', listboxId + '-' + i);
          li.setAttribute('aria-selected', 'false');
          li.textContent = s;
          li.addEventListener('mousedown', function (e) {
            e.preventDefault(); // prevent blur
            selectOption(s);
          });
          lb.appendChild(li);
        });
        lb.style.display = '';
        input.setAttribute('aria-expanded', 'true');
        liveRegion.textContent = matches.length + ' suggestion' + (matches.length !== 1 ? 's' : '') + ' available';
      }

      function closeLb() {
        lb.style.display = 'none';
        input.setAttribute('aria-expanded', 'false');
        input.removeAttribute('aria-activedescendant');
        activeId = null;
      }

      function selectOption(val) {
        input.value = val;
        closeLb();
        var form = input.closest('form');
        if (form) form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
      }

      function moveActive(dir) {
        var opts = Array.prototype.slice.call(lb.querySelectorAll('.ac-option'));
        if (!opts.length) return;
        var currentIdx = opts.findIndex(function (o) { return o.id === activeId; });
        var nextIdx = currentIdx + dir;
        if (nextIdx < 0) nextIdx = opts.length - 1;
        if (nextIdx >= opts.length) nextIdx = 0;
        opts.forEach(function (o) { o.setAttribute('aria-selected', 'false'); o.classList.remove('is-active'); });
        opts[nextIdx].setAttribute('aria-selected', 'true');
        opts[nextIdx].classList.add('is-active');
        activeId = opts[nextIdx].id;
        input.setAttribute('aria-activedescendant', activeId);
        opts[nextIdx].scrollIntoView({block: 'nearest'});
      }

      input.addEventListener('input', function () {
        renderListbox(getMatches(input.value));
      });

      input.addEventListener('focus', function () {
        if (input.value) renderListbox(getMatches(input.value));
      });

      input.addEventListener('blur', function () {
        setTimeout(closeLb, 150); // allow mousedown to fire first
      });

      input.addEventListener('keydown', function (e) {
        if (lb.style.display === 'none') return;
        if (e.key === 'ArrowDown') { e.preventDefault(); moveActive(1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); moveActive(-1); }
        else if (e.key === 'Enter' && activeId) {
          var active = document.getElementById(activeId);
          if (active) { e.preventDefault(); selectOption(active.textContent); }
        }
        else if (e.key === 'Escape') { closeLb(); }
      });
    });
  }

  function renderSearchHistory() {
    var KEY = 'cloth_search_history';
    var history = JSON.parse(localStorage.getItem(KEY) || '[]');
    if (!history.length) return;

    var hero = document.querySelector('.hero');
    if (!hero) return;

    var container = document.createElement('div');
    container.className = 'search-history';
    container.setAttribute('aria-label', 'Recent searches');

    var label = document.createElement('p');
    label.className = 'history-label';
    label.textContent = 'Recent searches:';
    container.appendChild(label);

    var list = document.createElement('ul');
    list.className = 'history-chips';

    history.forEach(function (query) {
      var li = document.createElement('li');
      var a = document.createElement('a');
      a.href = '/search?q=' + encodeURIComponent(query);
      a.className = 'history-chip';
      a.textContent = query;
      li.appendChild(a);
      list.appendChild(li);
    });

    container.appendChild(list);

    var clearBtn = document.createElement('button');
    clearBtn.className = 'history-clear';
    clearBtn.textContent = 'Clear history';
    clearBtn.addEventListener('click', function () {
      localStorage.removeItem(KEY);
      container.remove();
    });
    container.appendChild(clearBtn);

    var searchForm = hero.querySelector('.search-form');
    if (searchForm) {
      searchForm.insertAdjacentElement('afterend', container);
    }
  }

  // ------------------------------------------------------------------ //
  // Recently viewed                                                      //
  // ------------------------------------------------------------------ //
  var RECENTLY_VIEWED_KEY = 'cloth_recently_viewed';
  var RECENTLY_VIEWED_MAX = 20;

  function trackRecentlyViewed(item) {
    try {
      var items = JSON.parse(localStorage.getItem(RECENTLY_VIEWED_KEY) || '[]');
      items = items.filter(function (i) { return i.id !== item.id; });
      items.unshift(item);
      items = items.slice(0, RECENTLY_VIEWED_MAX);
      localStorage.setItem(RECENTLY_VIEWED_KEY, JSON.stringify(items));
    } catch (e) { /* localStorage unavailable */ }
  }

  function initRecentlyViewedTracking() {
    if (window._rvTrackingBound) return;
    window._rvTrackingBound = true;
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('.btn-view[data-rv-id]');
      if (!btn) return;
      trackRecentlyViewed({
        id: btn.dataset.rvId,
        name: btn.dataset.rvName,
        price: btn.dataset.rvPrice,
        retailer: btn.dataset.rvRetailer,
        image: btn.dataset.rvImage,
        url: btn.dataset.rvUrl
      });
    });
  }

  function renderRecentlyViewed() {
    var hero = document.querySelector('.hero');
    if (!hero) return;
    try {
      var items = JSON.parse(localStorage.getItem(RECENTLY_VIEWED_KEY) || '[]');
      if (!items.length) return;
      var shown = items.slice(0, 5);

      var section = document.createElement('section');
      section.className = 'recently-viewed';
      section.setAttribute('aria-label', 'Recently viewed');

      var heading = document.createElement('h2');
      heading.className = 'recently-viewed-heading';
      heading.textContent = 'Recently viewed';
      section.appendChild(heading);

      var ul = document.createElement('ul');
      ul.className = 'recently-viewed-list';

      shown.forEach(function (item) {
        var li = document.createElement('li');
        li.className = 'recently-viewed-item';

        var a = document.createElement('a');
        a.href = item.url;
        a.rel = 'noopener noreferrer';
        a.target = '_blank';
        a.className = 'recently-viewed-link';

        if (item.image) {
          var img = document.createElement('img');
          img.src = item.image;
          img.alt = item.name;
          img.loading = 'lazy';
          img.className = 'recently-viewed-img';
          img.addEventListener('error', function () { img.style.display = 'none'; });
          a.appendChild(img);
        }

        var nameEl = document.createElement('span');
        nameEl.className = 'recently-viewed-name';
        nameEl.textContent = item.name;
        a.appendChild(nameEl);

        if (item.price) {
          var priceEl = document.createElement('span');
          priceEl.className = 'recently-viewed-price';
          priceEl.textContent = item.price;
          a.appendChild(priceEl);
        }

        li.appendChild(a);
        ul.appendChild(li);
      });

      section.appendChild(ul);
      hero.insertAdjacentElement('afterend', section);
    } catch (e) { /* localStorage unavailable */ }
  }

  // ------------------------------------------------------------------ //
  // Saved items                                                          //
  // ------------------------------------------------------------------ //
  var SAVED_KEY = 'cloth_saved_items';

  function getSavedItems() {
    try {
      return JSON.parse(localStorage.getItem(SAVED_KEY) || '[]');
    } catch (e) {
      return [];
    }
  }

  function setSavedItems(items) {
    localStorage.setItem(SAVED_KEY, JSON.stringify(items));
  }

  function isItemSaved(id) {
    return getSavedItems().some(function (item) { return item.id === id; });
  }

  function updateSaveButtons(id, saved) {
    document.querySelectorAll('.btn-save[data-id="' + id + '"]').forEach(function (btn) {
      btn.setAttribute('aria-pressed', saved ? 'true' : 'false');
      if (saved) {
        btn.classList.add('is-saved');
        btn.textContent = '♥';
      } else {
        btn.classList.remove('is-saved');
        btn.textContent = '♡';
      }
    });
  }

  function updateSavedCount() {
    var count = getSavedItems().length;
    var countEl = document.getElementById('saved-count');
    if (countEl) countEl.textContent = count;
  }

  function toggleSaveItem(data) {
    var items = getSavedItems();
    var idx = -1;
    for (var i = 0; i < items.length; i++) {
      if (items[i].id === data.id) { idx = i; break; }
    }
    if (idx === -1) {
      items.push(data);
    } else {
      items.splice(idx, 1);
    }
    setSavedItems(items);
    updateSaveButtons(data.id, idx === -1);
    updateSavedCount();
    showToast(idx === -1 ? 'Saved ♥' : 'Removed');
  }

  function initSaveButtons() {
    document.querySelectorAll('.btn-save').forEach(function (btn) {
      if (btn._saveBound) return;
      btn._saveBound = true;
      var id = btn.dataset.id;
      var saved = isItemSaved(id);
      btn.setAttribute('aria-pressed', saved ? 'true' : 'false');
      if (saved) {
        btn.classList.add('is-saved');
        btn.textContent = '♥';
      }
      btn.addEventListener('click', function () {
        toggleSaveItem({
          id: btn.dataset.id,
          name: btn.dataset.name,
          price: btn.dataset.price,
          retailer: btn.dataset.retailer,
          image: btn.dataset.image,
          url: btn.dataset.url
        });
      });
    });
  }

  function initCopyLinkButtons() {
    document.querySelectorAll('.btn-copy-link').forEach(function (btn) {
      if (btn._copyBound) return;
      btn._copyBound = true;
      btn.addEventListener('click', function () {
        var url = btn.dataset.url;
        if (!url || !navigator.clipboard) return;
        navigator.clipboard.writeText(url).then(function () {
          var original = btn.textContent;
          btn.textContent = 'Copied!';
          btn.classList.add('is-copied');
          showToast('Copied!');
          setTimeout(function () {
            btn.textContent = original;
            btn.classList.remove('is-copied');
          }, 1500);
        });
      });
    });
  }

  function renderSavedPage() {
    var container = document.getElementById('saved-items-container');
    if (!container) return;
    renderSavedPageItems(getSavedItems(), container);
  }

  // ------------------------------------------------------------------ //
  // Share saved list via URL hash (WN-094)                             //
  // ------------------------------------------------------------------ //

  // ------------------------------------------------------------------ //
  // Collections                                                          //
  // ------------------------------------------------------------------ //
  var COLLECTIONS_KEY = 'cloth_collections';

  function getCollections() {
    try {
      return JSON.parse(localStorage.getItem(COLLECTIONS_KEY) || '[]');
    } catch (e) {
      return [];
    }
  }

  function setCollections(cols) {
    localStorage.setItem(COLLECTIONS_KEY, JSON.stringify(cols));
  }

  function generateCollectionId() {
    return 'col_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7);
  }

  function initCollections() {
    var chipsContainer = document.getElementById('collections-chips');
    var newBtn = document.getElementById('btn-new-collection');
    var container = document.getElementById('saved-items-container');
    if (!chipsContainer || !newBtn || !container) return;

    var activeCollectionId = '';

    function renderCollectionChips() {
      var cols = getCollections();
      chipsContainer.innerHTML = '';

      var allChip = document.createElement('button');
      allChip.type = 'button';
      allChip.className = 'collection-chip' + (activeCollectionId === '' ? ' active' : '');
      allChip.setAttribute('role', 'tab');
      allChip.setAttribute('aria-selected', activeCollectionId === '' ? 'true' : 'false');
      allChip.dataset.collectionId = '';
      allChip.textContent = 'All';
      allChip.addEventListener('click', function () {
        activeCollectionId = '';
        renderCollectionChips();
        renderFilteredItems();
      });
      chipsContainer.appendChild(allChip);

      cols.forEach(function (col) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'collection-chip' + (activeCollectionId === col.id ? ' active' : '');
        chip.setAttribute('role', 'tab');
        chip.setAttribute('aria-selected', activeCollectionId === col.id ? 'true' : 'false');
        chip.dataset.collectionId = col.id;
        chip.textContent = col.name;
        chip.addEventListener('click', function () {
          activeCollectionId = col.id;
          renderCollectionChips();
          renderFilteredItems();
        });

        var renameBtn = document.createElement('button');
        renameBtn.type = 'button';
        renameBtn.className = 'collection-chip-action';
        renameBtn.setAttribute('aria-label', 'Rename collection ' + col.name);
        renameBtn.textContent = '✎';
        (function (capturedCol) {
          renameBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            showDialog('Rename collection:', capturedCol.name).then(function (newName) {
              if (newName && newName.trim()) {
                var cols2 = getCollections();
                cols2 = cols2.map(function (c) {
                  if (c.id === capturedCol.id) { c.name = newName.trim(); }
                  return c;
                });
                setCollections(cols2);
                renderCollectionChips();
              }
            });
          });
        }(col));

        var deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'collection-chip-action collection-chip-delete';
        deleteBtn.setAttribute('aria-label', 'Delete collection ' + col.name);
        deleteBtn.textContent = '×';
        (function (capturedCol) {
          deleteBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            showConfirm('Delete collection "' + capturedCol.name + '"?').then(function (ok) {
              if (!ok) return;
              var cols2 = getCollections().filter(function (c) { return c.id !== capturedCol.id; });
              setCollections(cols2);
              if (activeCollectionId === capturedCol.id) { activeCollectionId = ''; }
              renderCollectionChips();
              renderFilteredItems();
            });
          });
        }(col));

        var wrap = document.createElement('span');
        wrap.className = 'collection-chip-wrap';
        wrap.appendChild(chip);
        wrap.appendChild(renameBtn);
        wrap.appendChild(deleteBtn);
        chipsContainer.appendChild(wrap);
      });
    }

    function getAssignableCollections(itemId) {
      return getCollections().map(function (col) {
        return {id: col.id, name: col.name, has: (col.itemIds || []).indexOf(itemId) !== -1};
      });
    }

    function renderFilteredItems() {
      var items = getSavedItems();
      if (activeCollectionId) {
        var col = getCollections().find(function (c) { return c.id === activeCollectionId; });
        var ids = col ? (col.itemIds || []) : [];
        items = items.filter(function (i) { return ids.indexOf(i.id) !== -1; });
      }
      renderSavedPageItems(items, container);
      addAssignButtons();
    }

    function addAssignButtons() {
      var items = getSavedItems();
      items.forEach(function (item) {
        var card = container.querySelector('.product-card');
        var infoEls = container.querySelectorAll('.product-info');
        infoEls.forEach(function (info) {
          var removeBtn = info.querySelector('.btn-remove-saved');
          if (!removeBtn || removeBtn.dataset.id !== item.id) return;
          if (info.querySelector('.btn-assign-collection')) return;

          var assignBtn = document.createElement('button');
          assignBtn.className = 'btn-assign-collection';
          assignBtn.setAttribute('aria-label', 'Assign ' + item.name + ' to a collection');
          assignBtn.textContent = '+ Collection';
          (function (capturedItemId) {
            assignBtn.addEventListener('click', function () {
              var cols = getCollections();
              if (!cols.length) {
                showDialog('Create a collection:', '').then(function (name) {
                  if (!name || !name.trim()) return;
                  var newCol = {id: generateCollectionId(), name: name.trim(), itemIds: [capturedItemId]};
                  cols.push(newCol);
                  setCollections(cols);
                  renderCollectionChips();
                });
                return;
              }
              var menu = assignBtn.nextSibling;
              if (menu && menu.classList && menu.classList.contains('collection-menu')) {
                menu.remove();
                return;
              }
              var colMenu = document.createElement('div');
              colMenu.className = 'collection-menu';
              cols.forEach(function (col) {
                var inCol = (col.itemIds || []).indexOf(capturedItemId) !== -1;
                var opt = document.createElement('button');
                opt.type = 'button';
                opt.className = 'collection-menu-item' + (inCol ? ' in-collection' : '');
                opt.textContent = (inCol ? '✓ ' : '') + col.name;
                opt.addEventListener('click', function () {
                  var cols2 = getCollections();
                  cols2 = cols2.map(function (c) {
                    if (c.id !== col.id) return c;
                    var ids = c.itemIds || [];
                    if (inCol) {
                      c.itemIds = ids.filter(function (i) { return i !== capturedItemId; });
                    } else {
                      if (ids.indexOf(capturedItemId) === -1) ids.push(capturedItemId);
                      c.itemIds = ids;
                    }
                    return c;
                  });
                  setCollections(cols2);
                  colMenu.remove();
                  if (activeCollectionId) { renderFilteredItems(); }
                });
                colMenu.appendChild(opt);
              });
              var newOpt = document.createElement('button');
              newOpt.type = 'button';
              newOpt.className = 'collection-menu-item collection-menu-new';
              newOpt.textContent = '+ New collection';
              newOpt.addEventListener('click', function () {
                showDialog('New collection name:', '').then(function (name) {
                  if (!name || !name.trim()) return;
                  var newCol = {id: generateCollectionId(), name: name.trim(), itemIds: [capturedItemId]};
                  var cols2 = getCollections();
                  cols2.push(newCol);
                  setCollections(cols2);
                  renderCollectionChips();
                  colMenu.remove();
                });
              });
              colMenu.appendChild(newOpt);
              assignBtn.insertAdjacentElement('afterend', colMenu);
            });
          }(item.id));

          info.insertBefore(assignBtn, info.querySelector('.saved-item-note'));
        });
      });
    }

    newBtn.addEventListener('click', function () {
      showDialog('New collection name:', '').then(function (name) {
        if (!name || !name.trim()) return;
        var cols = getCollections();
        cols.push({id: generateCollectionId(), name: name.trim(), itemIds: []});
        setCollections(cols);
        renderCollectionChips();
      });
    });

    renderCollectionChips();
    renderFilteredItems();
  }

  function renderSavedPageItems(items, container) {
    var clearBtn = document.getElementById('clear-saved-btn');

    if (!items.length) {
      container.innerHTML = '<p class="saved-empty">No saved items yet. Browse and tap ♡ to save items.</p>';
      if (clearBtn) clearBtn.style.display = 'none';
      return;
    }

    var ul = document.createElement('ul');
    ul.className = 'product-grid';
    ul.setAttribute('aria-label', 'Saved items');

    items.forEach(function (item) {
      var li = document.createElement('li');
      li.className = 'product-card';

      var imageWrap = document.createElement('div');
      imageWrap.className = 'product-image-wrap';

      var fallback = document.createElement('div');
      fallback.className = 'image-fallback';
      fallback.style.display = item.image ? 'none' : 'flex';
      var fallbackSpan = document.createElement('span');
      fallbackSpan.textContent = item.retailer;
      fallback.appendChild(fallbackSpan);

      if (item.image) {
        var img = document.createElement('img');
        img.src = item.image;
        img.alt = item.name;
        img.loading = 'lazy';
        img.addEventListener('error', function () {
          img.style.display = 'none';
          fallback.style.display = 'flex';
        });
        imageWrap.appendChild(img);
      }

      imageWrap.appendChild(fallback);

      var info = document.createElement('div');
      info.className = 'product-info';

      var nameEl = document.createElement('h2');
      nameEl.className = 'product-name';
      nameEl.textContent = item.name;

      var priceEl = document.createElement('p');
      priceEl.className = 'product-price';
      priceEl.textContent = item.price || 'Price not available';

      var retailerEl = document.createElement('p');
      retailerEl.className = 'product-retailer';
      retailerEl.textContent = item.retailer;

      var viewBtn = document.createElement('a');
      viewBtn.href = item.url;
      viewBtn.className = 'btn-view';
      viewBtn.rel = 'noopener noreferrer';
      viewBtn.target = '_blank';
      viewBtn.setAttribute('aria-label', 'View ' + item.name + ' at ' + item.retailer);
      viewBtn.textContent = 'View item';

      var removeBtn = document.createElement('button');
      removeBtn.className = 'btn-remove-saved';
      removeBtn.dataset.id = item.id;
      removeBtn.setAttribute('aria-label', 'Remove ' + item.name + ' from saved items');
      removeBtn.textContent = 'Remove';
      (function (capturedItem, capturedLi) {
        removeBtn.addEventListener('click', function () {
          var remaining = getSavedItems().filter(function (s) { return s.id !== capturedItem.id; });
          setSavedItems(remaining);
          capturedLi.remove();
          updateSavedCount();
          if (!remaining.length) {
            container.innerHTML = '<p class="saved-empty">No saved items yet. Browse and tap ♡ to save items.</p>';
            if (clearBtn) clearBtn.style.display = 'none';
          }
        });
      }(item, li));

      var outfitBtn = document.createElement('button');
      outfitBtn.className = 'btn-add-to-outfit';
      outfitBtn.dataset.id = item.id;
      outfitBtn.dataset.name = item.name;
      outfitBtn.dataset.price = item.price || '';
      outfitBtn.dataset.retailer = item.retailer || '';
      outfitBtn.dataset.image = item.image || '';
      outfitBtn.dataset.url = item.url || '';
      outfitBtn.setAttribute('aria-label', 'Add ' + item.name + ' to outfit');
      outfitBtn.textContent = '+ Outfit';

      var similarLink = document.createElement('a');
      similarLink.href = '/search?q=' + encodeURIComponent(deriveSimilarQuery(item.name));
      similarLink.className = 'btn-find-similar';
      similarLink.setAttribute('aria-label', 'Find items similar to ' + item.name);
      similarLink.textContent = 'Find similar';

      var noteTextarea = document.createElement('textarea');
      noteTextarea.className = 'saved-item-note';
      noteTextarea.placeholder = 'Add a note…';
      noteTextarea.setAttribute('aria-label', 'Note for ' + item.name);
      noteTextarea.value = item.note || '';
      noteTextarea.rows = 2;
      (function (capturedId) {
        noteTextarea.addEventListener('input', function () {
          var all = getSavedItems();
          all = all.map(function (s) {
            if (s.id === capturedId) { s.note = noteTextarea.value; }
            return s;
          });
          setSavedItems(all);
        });
      }(item.id));

      var tryOnBtn = null;
      if (_TRY_ON_ENABLED) {
        tryOnBtn = document.createElement('button');
        tryOnBtn.className = 'btn-try-on';
        tryOnBtn.dataset.garmentUrl = item.image || '';
        tryOnBtn.dataset.garmentName = item.name;
        tryOnBtn.setAttribute('aria-label', 'Try on ' + item.name);
        tryOnBtn.textContent = 'Try on';
      }

      var styleItBtn = document.createElement('button');
      styleItBtn.className = 'btn-style-it';
      styleItBtn.dataset.garmentUrl = item.image || '';
      styleItBtn.dataset.garmentName = item.name;
      styleItBtn.setAttribute('aria-label', 'Style ' + item.name + ' on canvas');
      styleItBtn.textContent = 'Style it';

      info.appendChild(nameEl);
      info.appendChild(priceEl);
      info.appendChild(retailerEl);
      info.appendChild(viewBtn);
      info.appendChild(removeBtn);
      info.appendChild(outfitBtn);
      info.appendChild(similarLink);
      if (tryOnBtn) info.appendChild(tryOnBtn);
      info.appendChild(styleItBtn);
      info.appendChild(noteTextarea);

      li.appendChild(imageWrap);
      li.appendChild(info);
      ul.appendChild(li);
    });

    container.innerHTML = '';
    container.appendChild(ul);
    initAddToOutfitButtons();
    initTryOnButtons();
    if (typeof window.initStyleItButtons === 'function') window.initStyleItButtons();

    if (clearBtn) {
      clearBtn.style.display = '';
      clearBtn.addEventListener('click', function () {
        setSavedItems([]);
        container.innerHTML = '<p class="saved-empty">No saved items yet. Browse and tap ♡ to save items.</p>';
        clearBtn.style.display = 'none';
        updateSavedCount();
      });
    }
  }

  function initShareSavedList() {
    var shareBtn = document.getElementById('share-saved-btn');
    var panel = document.getElementById('shared-saved-panel');
    if (!shareBtn || !panel) return;

    var items = getSavedItems();
    if (items.length) shareBtn.style.display = '';

    shareBtn.addEventListener('click', function () {
      var encoded = btoa(unescape(encodeURIComponent(JSON.stringify(items))));
      var url = window.location.origin + '/saved#v1:' + encoded;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(function () {
          shareBtn.textContent = 'Link copied!';
          setTimeout(function () { shareBtn.textContent = 'Share list'; }, 2000);
        });
      } else {
        showDialog('Copy this link to share your saved list:', url);
      }
    });

    var hash = window.location.hash;
    if (hash && hash.startsWith('#v1:')) {
      try {
        var b64 = hash.slice(4);
        var json = decodeURIComponent(escape(atob(b64)));
        var sharedItems = JSON.parse(json);
        if (Array.isArray(sharedItems) && sharedItems.length) {
          renderSharedSavedPanel(panel, sharedItems);
        }
      } catch (e) {
        // Invalid or corrupted fragment — silently ignore
      }
    }
  }

  function renderSharedSavedPanel(panel, sharedItems) {
    var heading = document.createElement('section');
    heading.className = 'shared-saved-section';
    var h2 = document.createElement('h2');
    h2.textContent = 'Shared saved list';
    var banner = document.createElement('p');
    banner.className = 'shared-saved-banner';
    banner.textContent = 'Shared list — save items you like to your own list.';
    heading.appendChild(h2);
    heading.appendChild(banner);

    var ul = document.createElement('ul');
    ul.className = 'product-grid';
    ul.setAttribute('aria-label', 'Shared saved items');

    sharedItems.forEach(function (item) {
      var li = document.createElement('li');
      li.className = 'product-card';

      var imageWrap = document.createElement('div');
      imageWrap.className = 'product-image-wrap';
      var fallback = document.createElement('div');
      fallback.className = 'image-fallback';
      fallback.style.display = item.image ? 'none' : 'flex';
      var fallbackSpan = document.createElement('span');
      fallbackSpan.textContent = item.retailer || '';
      fallback.appendChild(fallbackSpan);
      if (item.image) {
        var img = document.createElement('img');
        img.src = item.image;
        img.alt = item.name || '';
        img.loading = 'lazy';
        img.addEventListener('error', function () {
          img.style.display = 'none';
          fallback.style.display = 'flex';
        });
        imageWrap.appendChild(img);
      }
      imageWrap.appendChild(fallback);

      var info = document.createElement('div');
      info.className = 'product-info';
      var nameEl = document.createElement('h2');
      nameEl.className = 'product-name';
      nameEl.textContent = item.name || '';
      var priceEl = document.createElement('p');
      priceEl.className = 'product-price';
      priceEl.textContent = item.price || 'Price not available';
      var retailerEl = document.createElement('p');
      retailerEl.className = 'product-retailer';
      retailerEl.textContent = item.retailer || '';

      var saveBtn = document.createElement('button');
      saveBtn.className = 'btn-save';
      saveBtn.dataset.id = item.id;
      saveBtn.dataset.name = item.name || '';
      saveBtn.dataset.price = item.price || '';
      saveBtn.dataset.retailer = item.retailer || '';
      saveBtn.dataset.image = item.image || '';
      saveBtn.dataset.url = item.url || '';
      saveBtn.setAttribute('aria-label', 'Save ' + (item.name || ''));
      saveBtn.setAttribute('aria-pressed', 'false');
      saveBtn.textContent = '♡ Save';

      info.appendChild(nameEl);
      info.appendChild(priceEl);
      info.appendChild(retailerEl);
      info.appendChild(saveBtn);
      li.appendChild(imageWrap);
      li.appendChild(info);
      ul.appendChild(li);
    });

    heading.appendChild(ul);
    panel.appendChild(heading);
    panel.style.display = '';
    initSaveButtons();
  }

  // ------------------------------------------------------------------ //
  // Filter and sort (WN-012)                                            //
  // ------------------------------------------------------------------ //

  // WN-155: persist active filter state across AJAX searches
  var _filterState = {sort: 'relevance', min: '', max: '', keyword: ''};

  function _captureFilterState() {
    var activeChip = document.querySelector('.filter-chip.active:not(.retailer-chip)');
    _filterState.min = activeChip ? (activeChip.dataset.min || '') : '';
    _filterState.max = activeChip ? (activeChip.dataset.max || '') : '';
    _filterState.sort = (document.getElementById('sort-select') || {}).value || 'relevance';
    _filterState.keyword = ((document.getElementById('keyword-filter') || {}).value || '').toLowerCase().trim();
  }

  function _restoreFilterState() {
    var bar = document.getElementById('filter-sort-bar');
    if (!bar) return;
    if (_filterState.sort !== 'relevance') {
      var sortSel = document.getElementById('sort-select');
      if (sortSel) sortSel.value = _filterState.sort;
    }
    if (_filterState.min !== '' || _filterState.max !== '') {
      document.querySelectorAll('.filter-chip:not(.retailer-chip)').forEach(function (c) {
        var isMatch = (c.dataset.min || '') === _filterState.min && (c.dataset.max || '') === _filterState.max;
        c.classList.toggle('active', isMatch);
        c.setAttribute('aria-pressed', isMatch ? 'true' : 'false');
      });
    }
    if (_filterState.keyword) {
      var kw = document.getElementById('keyword-filter');
      if (kw) kw.value = _filterState.keyword;
    }
    var hasActive = _filterState.sort !== 'relevance' || _filterState.min !== '' || _filterState.max !== '' || _filterState.keyword !== '';
    _updateFilterBadge(hasActive);
    if (hasActive) applyFilterSort();
  }

  function _updateFilterBadge(hasActive) {
    var bar = document.getElementById('filter-sort-bar');
    if (!bar) return;
    var existing = bar.querySelector('.filter-clear-all');
    if (hasActive && !existing) {
      var clearBtn = document.createElement('button');
      clearBtn.type = 'button';
      clearBtn.className = 'filter-clear-all';
      clearBtn.textContent = 'Clear all';
      clearBtn.setAttribute('aria-label', 'Clear all filters');
      clearBtn.addEventListener('click', function () {
        _filterState = {sort: 'relevance', min: '', max: '', keyword: ''};
        document.querySelectorAll('.filter-chip').forEach(function (c) {
          c.classList.remove('active');
          c.setAttribute('aria-pressed', 'false');
        });
        var any = document.querySelector('.filter-chip[data-min=""][data-max=""]');
        if (any) { any.classList.add('active'); any.setAttribute('aria-pressed', 'true'); }
        var s = document.getElementById('sort-select');
        if (s) s.value = 'relevance';
        var k = document.getElementById('keyword-filter');
        if (k) k.value = '';
        applyFilterSort();
        clearBtn.remove();
      });
      bar.appendChild(clearBtn);
    } else if (!hasActive && existing) {
      existing.remove();
    }
  }

  function applyFilterSort() {
    var grid = document.getElementById('product-grid');
    if (!grid) return;

    var activeChip = document.querySelector('.filter-chip.active:not(.retailer-chip)');
    var minVal = activeChip ? activeChip.dataset.min : '';
    var maxVal = activeChip ? activeChip.dataset.max : '';

    // If no chip is active, check the price slider
    if (!activeChip) {
      var sliderMin = document.getElementById('price-range-min');
      var sliderMax = document.getElementById('price-range-max');
      if (sliderMin && sliderMax) {
        var sliderLo = Math.min(parseInt(sliderMin.value, 10), parseInt(sliderMax.value, 10));
        var sliderHi = Math.max(parseInt(sliderMin.value, 10), parseInt(sliderMax.value, 10));
        var atDefault = (sliderLo <= parseInt(sliderMin.min, 10) && sliderHi >= parseInt(sliderMax.max, 10));
        if (!atDefault) {
          minVal = String(sliderLo);
          maxVal = String(sliderHi + 0.01);
        }
      }
    }
    var sortVal = (document.getElementById('sort-select') || {}).value || 'relevance';
    var keyword = ((document.getElementById('keyword-filter') || {}).value || '').toLowerCase().trim();
    var activeRetailerChip = document.querySelector('.retailer-chip.active');
    var retailerFilter = activeRetailerChip ? activeRetailerChip.getAttribute('data-retailer-filter') : '';

    var cards = Array.prototype.slice.call(grid.querySelectorAll('.product-card'));

    // Show/hide based on price filter and keyword filter
    cards.forEach(function (card) {
      // Price filter
      var price = card.dataset.priceValue;
      var priceHide = false;
      if (minVal !== '' || maxVal !== '') {
        if (price === '') {
          priceHide = true;
        } else {
          var val = parseFloat(price);
          var min = minVal !== '' ? parseFloat(minVal) : -Infinity;
          var max = maxVal !== '' ? parseFloat(maxVal) : Infinity;
          priceHide = val < min || val >= max;
        }
      }
      // Keyword filter
      var keywordHide = false;
      if (keyword) {
        var name = (card.dataset.name || '').toLowerCase();
        var retailer = (card.dataset.retailer || '').toLowerCase();
        keywordHide = name.indexOf(keyword) === -1 && retailer.indexOf(keyword) === -1;
      }
      // Retailer chip filter
      var retailerHide = false;
      if (retailerFilter) {
        retailerHide = (card.dataset.retailer || '') !== retailerFilter;
      }
      card.hidden = priceHide || keywordHide || retailerHide;
    });

    // Sort visible cards
    if (sortVal !== 'relevance') {
      var visibleCards = cards.filter(function (c) { return !c.hidden; });
      if (sortVal === 'retailer_asc' || sortVal === 'retailer_desc') {
        visibleCards.sort(function (a, b) {
          var ra = (a.dataset.retailer || '').toLowerCase();
          var rb = (b.dataset.retailer || '').toLowerCase();
          if (ra < rb) return sortVal === 'retailer_asc' ? -1 : 1;
          if (ra > rb) return sortVal === 'retailer_asc' ? 1 : -1;
          return 0;
        });
      } else {
        visibleCards.sort(function (a, b) {
          var pa = a.dataset.priceValue !== '' ? parseFloat(a.dataset.priceValue) : (sortVal === 'price_asc' ? Infinity : -Infinity);
          var pb = b.dataset.priceValue !== '' ? parseFloat(b.dataset.priceValue) : (sortVal === 'price_asc' ? Infinity : -Infinity);
          return sortVal === 'price_asc' ? pa - pb : pb - pa;
        });
      }
      visibleCards.forEach(function (card) { grid.appendChild(card); });
    } else {
      // Restore original relevance order
      cards.sort(function (a, b) { return parseInt(a.dataset.position, 10) - parseInt(b.dataset.position, 10); });
      cards.forEach(function (card) { grid.appendChild(card); });
    }

    // Persist filter/sort in URL without adding to history
    var params = new URLSearchParams(window.location.search);
    if (sortVal !== 'relevance') { params.set('sort', sortVal); } else { params.delete('sort'); }
    if (minVal !== '' || maxVal !== '') {
      params.set('min_price', minVal);
      params.set('max_price', maxVal);
    } else {
      params.delete('min_price');
      params.delete('max_price');
    }
    var newUrl = window.location.pathname + '?' + params.toString();
    history.replaceState(history.state, '', newUrl);
    // WN-155: capture state after applying
    _captureFilterState();
    var hasActive = sortVal !== 'relevance' || minVal !== '' || maxVal !== '' || keyword !== '';
    _updateFilterBadge(hasActive);
  }

  function buildRetailerChips() {
    var bar = document.getElementById('filter-sort-bar');
    var grid = document.getElementById('product-grid');
    if (!bar || !grid) return;

    // Collect unique retailers from the result set
    var retailers = [];
    grid.querySelectorAll('.product-card').forEach(function (card) {
      var r = card.dataset.retailer || '';
      if (r && retailers.indexOf(r) === -1) retailers.push(r);
    });

    // Only show retailer chips when there are 2+ distinct retailers
    if (retailers.length < 2) return;

    retailers.sort();

    var group = document.createElement('div');
    group.className = 'filter-group retailer-filter-group';
    group.id = 'retailer-filter-group';

    var label = document.createElement('span');
    label.className = 'filter-label';
    label.id = 'retailer-filter-label';
    label.textContent = 'Retailer:';
    group.appendChild(label);

    var chipsDiv = document.createElement('div');
    chipsDiv.className = 'filter-chips retailer-chips';
    chipsDiv.setAttribute('role', 'group');
    chipsDiv.setAttribute('aria-labelledby', 'retailer-filter-label');

    // "All" chip
    var allChip = document.createElement('button');
    allChip.type = 'button';
    allChip.className = 'filter-chip retailer-chip active';
    allChip.setAttribute('data-retailer-filter', '');
    allChip.setAttribute('aria-pressed', 'true');
    allChip.textContent = 'All';
    chipsDiv.appendChild(allChip);

    retailers.forEach(function (r) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'filter-chip retailer-chip';
      chip.setAttribute('data-retailer-filter', r);
      chip.setAttribute('aria-pressed', 'false');
      // Display with original casing (capitalize first letter of each word)
      chip.textContent = r.replace(/\b\w/g, function (c) { return c.toUpperCase(); });
      chipsDiv.appendChild(chip);
    });

    group.appendChild(chipsDiv);
    bar.insertBefore(group, bar.firstChild);

    chipsDiv.querySelectorAll('.retailer-chip').forEach(function (chip) {
      chip.addEventListener('click', function () {
        chipsDiv.querySelectorAll('.retailer-chip').forEach(function (c) {
          c.classList.remove('active');
          c.setAttribute('aria-pressed', 'false');
        });
        chip.classList.add('active');
        chip.setAttribute('aria-pressed', 'true');
        applyFilterSort();
      });
    });
  }

  function initFilterSort() {
    buildRetailerChips();

    document.querySelectorAll('.filter-chip:not(.retailer-chip)').forEach(function (chip) {
      chip.addEventListener('click', function () {
        document.querySelectorAll('.filter-chip:not(.retailer-chip)').forEach(function (c) {
          c.classList.remove('active');
          c.setAttribute('aria-pressed', 'false');
        });
        chip.classList.add('active');
        chip.setAttribute('aria-pressed', 'true');
        applyFilterSort();
      });
    });

    var sortSelect = document.getElementById('sort-select');
    if (sortSelect) {
      sortSelect.addEventListener('change', applyFilterSort);
    }

    var keywordInput = document.getElementById('keyword-filter');
    if (keywordInput) {
      keywordInput.addEventListener('input', _debounce(applyFilterSort, 200));
    }

    // Restore filter/sort from URL params on page load
    var params = new URLSearchParams(window.location.search);
    var sort = params.get('sort');
    var minPrice = params.get('min_price');
    var maxPrice = params.get('max_price');

    if (sort && document.getElementById('sort-select')) {
      document.getElementById('sort-select').value = sort;
    }
    if (minPrice !== null || maxPrice !== null) {
      document.querySelectorAll('.filter-chip:not(.retailer-chip)').forEach(function (chip) {
        if (chip.dataset.min === (minPrice || '') && chip.dataset.max === (maxPrice || '')) {
          chip.classList.add('active');
          chip.setAttribute('aria-pressed', 'true');
        } else {
          chip.classList.remove('active');
          chip.setAttribute('aria-pressed', 'false');
        }
      });
    }

    if (sort || minPrice !== null) {
      applyFilterSort();
    }

    initPriceSlider();
  }

  // ------------------------------------------------------------------ //
  // Ajax / lazy search (WN-066)                                         //
  // ------------------------------------------------------------------ //

  // WN-137: simple debounce helper
  function _debounce(fn, delay) {
    var timer;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, delay);
    };
  }

  // Pure utility functions — canonical definitions live in cloth-pure.js (testable standalone).
  var escapeHtml = window.ClothPure.escapeHtml;
  var buildCacheAgeText = window.ClothPure.buildCacheAgeText;

  // ------------------------------------------------------------------ //
  // Inline dialog helpers (WN-131)                                       //
  // ------------------------------------------------------------------ //

  function _getAppDialog() {
    return document.getElementById('app-dialog');
  }

  // showDialog(title, defaultValue) → Promise<string|null>
  // Resolves with the input value on OK, null on Cancel/Escape.
  function showDialog(title, defaultValue) {
    return new Promise(function (resolve) {
      var dlg = _getAppDialog();
      if (!dlg) { resolve(window.prompt(title, defaultValue)); return; }

      var titleEl = dlg.querySelector('#app-dialog-title');
      var msgEl = dlg.querySelector('#app-dialog-message');
      var inputEl = dlg.querySelector('#app-dialog-input');
      var cancelBtn = dlg.querySelector('#app-dialog-cancel');
      var okBtn = dlg.querySelector('#app-dialog-ok');

      titleEl.textContent = title;
      msgEl.hidden = true;
      inputEl.hidden = false;
      inputEl.value = defaultValue || '';
      okBtn.textContent = 'OK';

      var resolved = false;
      function done(val) {
        if (resolved) return;
        resolved = true;
        dlg.close();
        resolve(val);
      }

      function onCancel() { done(null); }
      function onOk(e) {
        e.preventDefault();
        done(inputEl.value.trim() || null);
      }
      function onKeydown(e) {
        if (e.key === 'Escape') { done(null); }
      }
      function onClose() { if (!resolved) done(null); }

      cancelBtn.addEventListener('click', onCancel, {once: true});
      dlg.querySelector('.app-dialog-form').addEventListener('submit', onOk, {once: true});
      dlg.addEventListener('keydown', onKeydown, {once: true});
      dlg.addEventListener('close', onClose, {once: true});

      dlg.showModal();
      inputEl.focus();
      inputEl.select();
    });
  }

  // showConfirm(message) → Promise<boolean>
  // Resolves true on OK, false on Cancel/Escape.
  function showConfirm(message) {
    return new Promise(function (resolve) {
      var dlg = _getAppDialog();
      if (!dlg) { resolve(window.confirm(message)); return; }

      var titleEl = dlg.querySelector('#app-dialog-title');
      var msgEl = dlg.querySelector('#app-dialog-message');
      var inputEl = dlg.querySelector('#app-dialog-input');
      var cancelBtn = dlg.querySelector('#app-dialog-cancel');
      var okBtn = dlg.querySelector('#app-dialog-ok');

      titleEl.textContent = message;
      msgEl.hidden = true;
      inputEl.hidden = true;
      okBtn.textContent = 'Confirm';

      var resolved = false;
      function done(val) {
        if (resolved) return;
        resolved = true;
        dlg.close();
        resolve(val);
      }

      function onCancel() { done(false); }
      function onOk(e) { e.preventDefault(); done(true); }
      function onKeydown(e) { if (e.key === 'Escape') done(false); }
      function onClose() { if (!resolved) done(false); }

      cancelBtn.addEventListener('click', onCancel, {once: true});
      dlg.querySelector('.app-dialog-form').addEventListener('submit', onOk, {once: true});
      dlg.addEventListener('keydown', onKeydown, {once: true});
      dlg.addEventListener('close', onClose, {once: true});

      dlg.showModal();
      okBtn.focus();
    });
  }

  // WN-160: generate related search chips from a query
  var _COLOUR_SYNS = {
    'navy': ['navy blue', 'dark blue', 'indigo'],
    'black': ['charcoal', 'onyx'],
    'white': ['cream', 'ivory', 'off-white'],
    'grey': ['gray', 'charcoal', 'slate'],
    'red': ['burgundy', 'crimson', 'scarlet'],
    'green': ['olive', 'emerald', 'sage'],
    'blue': ['cobalt', 'royal blue', 'denim blue'],
    'brown': ['tan', 'camel', 'chocolate'],
    'pink': ['blush', 'rose', 'mauve'],
    'beige': ['nude', 'sand', 'oatmeal']
  };
  var _GARMENT_SYNS = {
    'chinos': ['trousers', 'shorts', 'joggers'],
    'jeans': ['denim trousers', 'skinny jeans', 'wide-leg jeans'],
    'dress': ['midi dress', 'maxi dress', 'mini dress'],
    'jacket': ['blazer', 'coat', 'cardigan'],
    'shirt': ['blouse', 'top', 'tunic'],
    'jumper': ['sweater', 'knitwear', 'pullover'],
    'skirt': ['midi skirt', 'maxi skirt', 'pleated skirt'],
    'suit': ['two-piece', 'trouser suit'],
    'coat': ['overcoat', 'trench coat', 'mac'],
    'boots': ['ankle boots', 'knee-high boots', 'heeled boots'],
    'trainers': ['sneakers', 'running shoes', 'casual shoes']
  };
  var _GENDER_MODS = ["women's", "men's"];

  function _deriveRelatedSearches(query) {
    var q = query.toLowerCase();
    var results = [];

    // Colour synonyms
    Object.keys(_COLOUR_SYNS).forEach(function (colour) {
      if (q.indexOf(colour) !== -1) {
        _COLOUR_SYNS[colour].forEach(function (syn) {
          results.push(q.replace(colour, syn));
        });
      }
    });

    // Garment synonyms
    Object.keys(_GARMENT_SYNS).forEach(function (garment) {
      if (q.indexOf(garment) !== -1) {
        _GARMENT_SYNS[garment].forEach(function (syn) {
          results.push(q.replace(garment, syn));
        });
      }
    });

    // Gender variants
    _GENDER_MODS.forEach(function (mod) {
      if (q.indexOf(mod) === -1) results.push(q + ' ' + mod);
    });

    // Deduplicate and filter out the original query
    var seen = {};
    seen[q] = true;
    var deduped = [];
    results.forEach(function (r) {
      var k = r.toLowerCase().trim();
      if (!seen[k]) { seen[k] = true; deduped.push(k); }
    });

    return deduped.slice(0, 6);
  }

  function _initRelatedSearchChips(query) {
    var grid = document.getElementById('product-grid');
    if (!grid || !query) return;
    var existing = document.getElementById('related-searches');
    if (existing) existing.remove();

    var chips = _deriveRelatedSearches(query);
    if (!chips.length) return;

    var section = document.createElement('div');
    section.id = 'related-searches';
    section.className = 'related-searches';
    section.setAttribute('aria-label', 'Related searches');

    var label = document.createElement('p');
    label.className = 'related-searches-label';
    label.textContent = 'Related searches:';
    section.appendChild(label);

    var list = document.createElement('ul');
    list.className = 'related-chips';
    chips.forEach(function (chip) {
      var li = document.createElement('li');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'related-chip';
      btn.textContent = chip;
      btn.addEventListener('click', function () {
        doAjaxSearch(chip, null, false, true);
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
    section.appendChild(list);

    var lmWrap = document.getElementById('load-more-wrap');
    if (lmWrap) {
      grid.parentNode.insertBefore(section, lmWrap);
    } else {
      grid.parentNode.appendChild(section);
    }
  }

  function renderResultsRegion(data) {
    var region = document.getElementById('results-region');
    if (!region) {
      // Navigating from a page with no results region (e.g. home page) — build one
      var main = document.querySelector('main');
      if (!main) return;
      region = document.createElement('div');
      region.id = 'results-region';
      main.innerHTML = '';
      main.appendChild(region);
    }

    var countLabel = (data.result_count === 1) ? '1 result' : (data.result_count + ' results');
    var headerHtml = '<section class="results-header" data-query="' + escapeHtml(data.query) + '">'
      + '<h1>' + countLabel + ' for <em>' + escapeHtml(data.query) + '</em></h1>';

    if (data.cache_age_minutes !== null && data.cache_age_minutes !== undefined && !data.error_message) {
      headerHtml += '<p class="meta">'
        + buildCacheAgeText(data.cache_age_minutes)
        + '<a href="/search?q=' + encodeURIComponent(data.query) + '&amp;fresh=true">Refresh</a>'
        + '</p>';
    }

    if (data.error_message) {
      headerHtml += '<p class="error-message" role="alert">' + escapeHtml(data.error_message) + '</p>';
    }

    headerHtml += '</section>';

    var bodyHtml = '';
    if (data.products && data.products.length > 0) {
      var _COLOR_SWATCH_MAP = {
        'Black': '#222', 'White': '#f5f5f5', 'Navy': '#1a1f36', 'Grey': '#888',
        'Red': '#c0392b', 'Green': '#27ae60', 'Blue': '#2980b9', 'Brown': '#7b4f3a', 'Cream': '#f5f0e8'
      };
      var _LIGHT_COLORS = ['White', 'Cream'];
      var colorNames = ['Black', 'White', 'Navy', 'Grey', 'Red', 'Green', 'Blue', 'Brown', 'Cream'];
      var colorChipsHtml = colorNames.map(function (c) {
        var hex = _COLOR_SWATCH_MAP[c] || '#ccc';
        var border = _LIGHT_COLORS.indexOf(c) !== -1 ? ';border:1px solid #ccc' : '';
        var swatchStyle = 'background:' + hex + border;
        return '<button type="button" class="filter-chip color-chip" data-color="' + c + '" aria-pressed="false">'
          + '<span class="color-swatch" style="' + swatchStyle + '" aria-hidden="true"></span>' + c + '</button>';
      }).join('');
      var genderChipsHtml = ["Women's", "Men's", 'Unisex'].map(function (g) {
        return '<button type="button" class="filter-chip gender-chip" data-gender="' + g + '" aria-pressed="false">' + g + '</button>';
      }).join('');
      var categoryChipsHtml = ['Tops', 'Bottoms', 'Outerwear', 'Footwear', 'Accessories'].map(function (cat) {
        return '<button type="button" class="filter-chip category-chip" data-category="' + cat + '" aria-pressed="false">' + cat + '</button>';
      }).join('');
      var sizeNames = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'UK 6', 'UK 8', 'UK 10', 'UK 12', 'UK 14', 'UK 16', 'UK 18', 'UK 20'];
      var sizeChipsHtml = sizeNames.map(function (s) {
        return '<button type="button" class="filter-chip size-chip" data-size="' + s + '" aria-pressed="false">' + s + '</button>';
      }).join('');
      bodyHtml = '<div class="filter-sort-bar" id="filter-sort-bar" aria-label="Filter and sort results">'
        + '<div class="color-filter-group" role="group" aria-label="Color filter">'
        + '<span class="filter-label">Color:</span>'
        + '<div class="filter-chips color-chips">' + colorChipsHtml + '</div>'
        + '</div>'
        + '<div class="gender-filter-group" role="group" aria-label="Gender filter">'
        + '<span class="filter-label">For:</span>'
        + '<div class="filter-chips gender-chips">' + genderChipsHtml + '</div>'
        + '</div>'
        + '<div class="category-filter-group" role="group" aria-label="Category filter">'
        + '<span class="filter-label">Category:</span>'
        + '<div class="filter-chips category-chips">' + categoryChipsHtml + '</div>'
        + '</div>'
        + '<div class="size-filter-group" role="group" aria-label="Size filter">'
        + '<span class="filter-label">Size:</span>'
        + '<div class="filter-chips size-chips">' + sizeChipsHtml + '</div>'
        + '</div>'
        + '<div class="filter-group">'
        + '<span class="filter-label" id="price-filter-label">Price:</span>'
        + '<div class="filter-chips" role="group" aria-labelledby="price-filter-label">'
        + '<button type="button" class="filter-chip active" data-min="" data-max="" aria-pressed="true">Any price</button>'
        + '<button type="button" class="filter-chip" data-min="0" data-max="50" aria-pressed="false">Under £50</button>'
        + '<button type="button" class="filter-chip" data-min="50" data-max="100" aria-pressed="false">£50–£100</button>'
        + '<button type="button" class="filter-chip" data-min="100" data-max="200" aria-pressed="false">£100–£200</button>'
        + '<button type="button" class="filter-chip" data-min="200" data-max="" aria-pressed="false">£200+</button>'
        + '</div></div>'
        + '<div class="price-slider-group" id="price-slider-group" style="display:none">'
        + '<span class="filter-label">Range:</span>'
        + '<div class="price-slider-wrap">'
        + '<input type="range" id="price-range-min" class="price-range" min="0" max="500" value="0" step="1" aria-label="Minimum price">'
        + '<input type="range" id="price-range-max" class="price-range" min="0" max="500" value="500" step="1" aria-label="Maximum price">'
        + '</div>'
        + '<span class="price-slider-display" id="price-slider-display">£0 – £500</span>'
        + '</div>'
        + '<div class="sort-group">'
        + '<label for="sort-select" class="filter-label">Sort:</label>'
        + '<select id="sort-select" class="sort-select">'
        + '<option value="relevance">Relevance</option>'
        + '<option value="price_asc">Price: Low–High</option>'
        + '<option value="price_desc">Price: High–Low</option>'
        + '<option value="retailer_asc">Retailer: A–Z</option>'
        + '<option value="retailer_desc">Retailer: Z–A</option>'
        + '</select></div>'
        + '<div class="keyword-group">'
        + '<label for="keyword-filter" class="filter-label">Filter:</label>'
        + '<input type="text" id="keyword-filter" class="keyword-filter" placeholder="e.g. linen" aria-label="Filter results by keyword">'
        + '</div>'
        + '<div class="density-toggle" role="group" aria-label="Grid density">'
        + '<button type="button" class="density-btn" data-density="compact" aria-label="Compact grid" title="Compact">&#9638;</button>'
        + '<button type="button" class="density-btn" data-density="comfortable" aria-label="Comfortable grid" title="Comfortable">&#9636;</button>'
        + '<button type="button" class="density-btn" data-density="large" aria-label="Large grid" title="Large">&#9634;</button>'
        + '</div></div>';
      bodyHtml += '<ul class="product-grid" id="product-grid" aria-label="Search results">'
        + (data.cards_html || '')
        + '</ul>';
      if (data.has_more) {
        bodyHtml += '<div class="load-more-wrap" id="load-more-wrap">'
          + '<button type="button" class="btn-load-more" id="btn-load-more"'
          + ' data-query="' + escapeHtml(data.query) + '" data-next-start="10">Load more results</button>'
          + '</div>';
      }
    } else if (!data.error_message) {
      var suggestions = (data.llm_suggestions && data.llm_suggestions.length)
        ? data.llm_suggestions
        : ['navy chinos', 'floral midi dress', 'oversized cream jumper', 'wool coat', 'white trainers', 'smart casual shirt'];
      var suggestionLabel = (data.llm_suggestions && data.llm_suggestions.length)
        ? '<p>Claude suggests trying:</p>'
        : '<p>Try one of these searches:</p>';
      bodyHtml = '<section class="empty-state">'
        + '<h2>No results found</h2>'
        + '<p>We couldn\'t find any matching items for <em>' + escapeHtml(data.query) + '</em>.</p>'
        + suggestionLabel
        + '<ul class="example-searches" aria-label="Suggested searches">'
        + suggestions.map(function (ex) {
          return '<li><a href="/search?q=' + encodeURIComponent(ex) + '" class="example-chip">' + escapeHtml(ex) + '</a></li>';
        }).join('')
        + '</ul></section>';
    }

    region.innerHTML = headerHtml + bodyHtml;

    // Re-init image fallback handlers for dynamically added cards
    region.querySelectorAll('.product-image-wrap img').forEach(function (img) {
      img.addEventListener('error', function () {
        img.style.display = 'none';
        var fallback = img.nextElementSibling;
        if (fallback && fallback.classList.contains('image-fallback')) {
          fallback.style.display = 'flex';
        }
      });
      if (img.complete && !img.naturalWidth) {
        img.dispatchEvent(new Event('error'));
      }
    });

    initSaveButtons();
    initCopyLinkButtons();
    initAddToOutfitButtons();
    initTryOnButtons();
    if (typeof window.initStyleItButtons === 'function') window.initStyleItButtons();
    initFilterSort();
    initColorFilter();
    initGenderFilter();
    initCategoryFilter();
    initSizeFilter();
    initDensityToggle();
    initLoadMore();
    initRefineBar();
    _syncCompareButtons();
    saveSearchToHistory(data.query);
    updateSavedCount();
    updateOutfitsCount();
    _restoreFilterState(); // WN-155: re-apply saved filter state
    if (data.products && data.products.length > 0) {
      _initRelatedSearchChips(data.query); // WN-160
    }
  }

  function setSearchButtonState(form, loading) {
    var btn = form.querySelector('button[type="submit"]');
    if (!btn) return;
    if (loading) {
      btn.dataset.originalLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Searching…';
      btn.classList.add('is-loading');
    } else {
      btn.disabled = false;
      btn.classList.remove('is-loading');
      if (btn.dataset.originalLabel) btn.textContent = btn.dataset.originalLabel;
    }
  }

  // Tracks the AbortController for an in-flight phase-2 fetch so new searches cancel it
  var _phase2Controller = null;

  function _cancelPhase2() {
    if (_phase2Controller) {
      _phase2Controller.abort();
      _phase2Controller = null;
    }
    var ind = document.getElementById('phase2-loading');
    if (ind && ind.parentNode) ind.parentNode.removeChild(ind);
  }

  // Fire the LLM-expanded search and append net-new cards below the phase-1 grid
  function _runPhase2(query, phase1Ids) {
    if (_phase2Controller) return;
    var grid = document.querySelector('.product-grid');
    if (!grid) return;

    _phase2Controller = new AbortController();

    var indicator = document.createElement('li');
    indicator.id = 'phase2-loading';
    indicator.className = 'phase2-loading';
    indicator.textContent = 'Finding more with AI…';
    grid.appendChild(indicator);

    fetch('/search?q=' + encodeURIComponent(query) + '&format=json&expand=true', {signal: _phase2Controller.signal})
      .then(function (res) { return res.json(); })
      .then(function (data) {
        _phase2Controller = null;
        var ind = document.getElementById('phase2-loading');
        if (ind && ind.parentNode) ind.parentNode.removeChild(ind);
        if (!data.cards_html || !data.product_ids) return;

        // Parse phase-2 HTML, filter out IDs already shown in phase 1
        var tmp = document.createElement('ul');
        tmp.innerHTML = data.cards_html;
        var newCards = Array.from(tmp.querySelectorAll('[data-product-id]')).filter(function (el) {
          return !phase1Ids.has(el.getAttribute('data-product-id'));
        });
        if (newCards.length === 0) return;

        var currentGrid = document.querySelector('.product-grid');
        if (!currentGrid) return;
        newCards.forEach(function (card) { currentGrid.appendChild(card); });

        // Re-init interactive features on the newly appended cards
        initSaveButtons();
        initCopyLinkButtons();
        initAddToOutfitButtons();
        initTryOnButtons();
        if (typeof window.initStyleItButtons === 'function') window.initStyleItButtons();
        _syncCompareButtons();
      })
      .catch(function () {
        _phase2Controller = null;
        var ind = document.getElementById('phase2-loading');
        if (ind && ind.parentNode) ind.parentNode.removeChild(ind);
      });
  }

  // WN-153: skeleton cards during phase-1 fetch
  function _showSkeletons(query) {
    var region = document.getElementById('results-region');
    if (!region) {
      var main = document.querySelector('main');
      if (!main) return;
      region = document.createElement('div');
      region.id = 'results-region';
      main.innerHTML = '';
      main.appendChild(region);
    }
    var skeletonItems = '';
    for (var i = 0; i < 6; i++) {
      skeletonItems += '<li class="product-card skeleton-card" aria-hidden="true">'
        + '<div class="skeleton-image"></div>'
        + '<div class="skeleton-body">'
        + '<div class="skeleton-line skeleton-line--title"></div>'
        + '<div class="skeleton-line skeleton-line--price"></div>'
        + '<div class="skeleton-line skeleton-line--retailer"></div>'
        + '</div>'
        + '</li>';
    }
    region.innerHTML = '<section class="results-header" data-query="' + escapeHtml(query) + '">'
      + '<h1>Searching for <em>' + escapeHtml(query) + '</em>…</h1>'
      + '</section>'
      + '<ul class="product-grid skeleton-grid" id="product-grid" aria-label="Loading results" aria-busy="true">'
      + skeletonItems
      + '</ul>';
  }

  // _skipPhase2: pass true for chip-augmented searches where the term is already explicit
  function doAjaxSearch(query, form, _isRetry, _skipPhase2) {
    _cancelPhase2(); // abort any previous phase-2 in flight

    // Show skeleton cards immediately (WN-153)
    if (!_isRetry) _showSkeletons(query);

    // Phase 1: direct search without LLM expansion — fast first render
    var url = '/search?q=' + encodeURIComponent(query) + '&format=json&expand=false';
    var timers = [];

    function clearTimers() { timers.forEach(function (t) { clearTimeout(t); }); }

    if (form) {
      setSearchButtonState(form, true);
      // Progressive messages so a slow first search doesn't feel like a hang
      timers.push(setTimeout(function () {
        var btn = form.querySelector('button[type="submit"]');
        if (btn && btn.classList.contains('is-loading')) btn.textContent = 'AI is expanding your search…';
      }, 4000));
      timers.push(setTimeout(function () {
        var btn = form.querySelector('button[type="submit"]');
        if (btn && btn.classList.contains('is-loading')) btn.textContent = 'Still searching — first searches may take a moment…';
      }, 10000));
    }

    fetch(url)
      .then(function (res) { return res.json(); })
      .then(function (data) {
        clearTimers();

        // Retry on server-side timeout errors (e.g. Render.com cold-start first request)
        if (data.error_message && !_isRetry) {
          setTimeout(function () { doAjaxSearch(query, form, true, _skipPhase2); }, 800);
          return;
        }

        if (form) setSearchButtonState(form, false);
        history.pushState({query: data.query, type: 'search'}, '', '/search?q=' + encodeURIComponent(data.query));
        var headerInput = document.querySelector('.header-search input[name="q"]');
        if (headerInput) headerInput.value = data.query;
        renderResultsRegion(data);

        // Phase 2: fetch LLM-expanded results and append net-new cards
        if (!_skipPhase2 && data.expand_available && data.product_ids && data.product_ids.length > 0) {
          _runPhase2(data.query, new Set(data.product_ids));
        }
      })
      .catch(function () {
        clearTimers();
        if (form) setSearchButtonState(form, false);
        if (!_isRetry) {
          // Retry once — handles cold-start failures before falling back to full nav
          setTimeout(function () { doAjaxSearch(query, form, true, _skipPhase2); }, 800);
        } else {
          window.location.href = '/search?q=' + encodeURIComponent(query);
        }
      });
  }

  function initAjaxSearch() {
    if (!window.fetch || !window.history || !window.history.pushState) return;

    document.querySelectorAll('form[action="/search"]').forEach(function (form) {
      if (form._ajaxBound) return;
      form._ajaxBound = true;
      form.addEventListener('submit', function (e) {
        var input = form.querySelector('input[name="q"]');
        var query = input ? input.value.trim() : '';
        if (!query) return;
        e.preventDefault();
        doAjaxSearch(query, form);
      });
    });

    // Seed history state so back button works from a server-rendered results page
    var resultsRegion = document.getElementById('results-region');
    if (resultsRegion) {
      var currentHeader = resultsRegion.querySelector('.results-header');
      if (currentHeader && currentHeader.dataset.query) {
        history.replaceState({query: currentHeader.dataset.query, type: 'search'}, '');
      }
    }
  }

  // ------------------------------------------------------------------ //
  // Outfit boards (WN-099)                                              //
  // ------------------------------------------------------------------ //
  var OUTFITS_KEY = 'cloth_outfits';

  function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  function getOutfits() {
    try {
      return JSON.parse(localStorage.getItem(OUTFITS_KEY) || '[]');
    } catch (e) {
      return [];
    }
  }

  function setOutfits(outfits) {
    localStorage.setItem(OUTFITS_KEY, JSON.stringify(outfits));
  }

  function updateOutfitsCount() {
    var countEl = document.getElementById('outfits-count');
    if (countEl) countEl.textContent = getOutfits().length;
  }

  function createOutfit(name) {
    var outfit = {
      id: generateId(),
      name: name,
      createdAt: new Date().toISOString(),
      items: []
    };
    var outfits = getOutfits();
    outfits.push(outfit);
    setOutfits(outfits);
    updateOutfitsCount();
    return outfit;
  }

  function deleteOutfit(id) {
    var outfits = getOutfits().filter(function (o) { return o.id !== id; });
    setOutfits(outfits);
    updateOutfitsCount();
  }

  function renameOutfit(id, newName) {
    var outfits = getOutfits();
    outfits.forEach(function (o) { if (o.id === id) o.name = newName; });
    setOutfits(outfits);
  }

  function addItemToOutfit(outfitId, item) {
    var outfits = getOutfits();
    outfits.forEach(function (o) {
      if (o.id === outfitId) {
        var alreadyIn = o.items.some(function (i) { return i.id === item.id; });
        if (!alreadyIn) o.items.push(item);
      }
    });
    setOutfits(outfits);
  }

  function removeItemFromOutfit(outfitId, itemId) {
    var outfits = getOutfits();
    outfits.forEach(function (o) {
      if (o.id === outfitId) {
        o.items = o.items.filter(function (i) { return i.id !== itemId; });
      }
    });
    setOutfits(outfits);
  }

  function buildOutfitBoardHtml(outfit) {
    var itemsHtml = '';
    if (outfit.items.length) {
      itemsHtml = '<ul class="outfit-mini-grid" aria-label="Items in ' + escapeHtml(outfit.name) + '">';
      outfit.items.forEach(function (item) {
        var imgHtml = item.image
          ? '<img src="' + escapeHtml(item.image) + '" alt="' + escapeHtml(item.name) + '" loading="lazy">'
          : '<div class="outfit-item-fallback">' + escapeHtml(item.retailer) + '</div>';
        itemsHtml += '<li class="outfit-mini-item" data-item-id="' + escapeHtml(item.id) + '">'
          + '<div class="outfit-mini-image">' + imgHtml + '</div>'
          + '<p class="outfit-mini-name">' + escapeHtml(item.name) + '</p>'
          + '<p class="outfit-mini-price">' + escapeHtml(item.price || '') + '</p>'
          + '<button class="btn-remove-outfit-item" data-outfit-id="' + escapeHtml(outfit.id) + '" data-item-id="' + escapeHtml(item.id) + '" aria-label="Remove ' + escapeHtml(item.name) + ' from outfit">Remove</button>'
          + (_TRY_ON_ENABLED
            ? '<button class="btn-try-on"'
              + ' data-garment-url="' + escapeHtml(item.image || '') + '"'
              + ' data-garment-name="' + escapeHtml(item.name) + '"'
              + ' aria-label="Try on ' + escapeHtml(item.name) + '">Try on</button>'
            : '')
          + '<button class="btn-style-it"'
          + ' data-garment-url="' + escapeHtml(item.image || '') + '"'
          + ' data-garment-name="' + escapeHtml(item.name) + '"'
          + ' aria-label="Style ' + escapeHtml(item.name) + ' on canvas">Style it</button>'
          + '</li>';
      });
      itemsHtml += '</ul>';
    } else {
      itemsHtml = '<p class="outfit-empty-items">No items yet. Add items from search results or saved items.</p>';
    }

    return '<article class="outfit-board" data-outfit-id="' + escapeHtml(outfit.id) + '" aria-label="Outfit board: ' + escapeHtml(outfit.name) + '">'
      + '<div class="outfit-board-header">'
      + '<h2 class="outfit-board-name">' + escapeHtml(outfit.name) + '</h2>'
      + '<div class="outfit-board-controls">'
      + '<button class="btn-rename-outfit" data-outfit-id="' + escapeHtml(outfit.id) + '" aria-label="Rename outfit ' + escapeHtml(outfit.name) + '">Rename</button>'
      + '<button class="btn-share-outfit" data-outfit-id="' + escapeHtml(outfit.id) + '" aria-label="Share outfit ' + escapeHtml(outfit.name) + '">Share</button>'
      + '<button class="btn-complete-outfit" data-outfit-id="' + escapeHtml(outfit.id) + '" aria-label="Complete outfit ' + escapeHtml(outfit.name) + '"'
      + (outfit.items.length === 0 ? ' disabled' : '') + '>Complete this outfit</button>'
      + '<button class="btn-open-canvas" data-outfit-id="' + escapeHtml(outfit.id) + '" '
      + 'aria-label="Open ' + escapeHtml(outfit.name) + ' in style canvas"'
      + (outfit.items.length === 0 ? ' disabled' : '') + '>Open in canvas</button>'
      + '<button class="btn-delete-outfit" data-outfit-id="' + escapeHtml(outfit.id) + '" aria-label="Delete outfit ' + escapeHtml(outfit.name) + '">Delete</button>'
      + '<button class="btn-shop-all-outfit" data-outfit-id="' + escapeHtml(outfit.id) + '" aria-label="Shop the outfit ' + escapeHtml(outfit.name) + ' — open all items"'
      + (outfit.items.length === 0 ? ' disabled' : '') + '>Shop all</button>'
      + '</div>'
      + '</div>'
      + itemsHtml
      + '<div class="outfit-suggestions" id="outfit-suggestions-' + escapeHtml(outfit.id) + '" hidden></div>'
      + '</article>';
  }

  function renderOutfitsPage() {
    var container = document.getElementById('outfits-container');
    if (!container) return;

    var outfits = getOutfits();

    if (!outfits.length) {
      container.innerHTML = '<p class="outfits-empty">No outfit boards yet. Create one to start collecting items.</p>';
      return;
    }

    var html = '';
    outfits.forEach(function (outfit) {
      html += buildOutfitBoardHtml(outfit);
    });
    container.innerHTML = html;

    // Wire up image fallbacks
    container.querySelectorAll('.outfit-mini-image img').forEach(function (img) {
      img.addEventListener('error', function () {
        img.style.display = 'none';
        var fallback = document.createElement('div');
        fallback.className = 'outfit-item-fallback';
        img.parentNode.appendChild(fallback);
      });
    });

    // Wire up remove-item buttons
    container.querySelectorAll('.btn-remove-outfit-item').forEach(function (btn) {
      btn.addEventListener('click', function () {
        removeItemFromOutfit(btn.dataset.outfitId, btn.dataset.itemId);
        renderOutfitsPage();
      });
    });

    // Wire up rename buttons
    container.querySelectorAll('.btn-rename-outfit').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var board = btn.closest('.outfit-board');
        var nameEl = board ? board.querySelector('.outfit-board-name') : null;
        var currentName = nameEl ? nameEl.textContent : '';
        showDialog('Rename outfit:', currentName).then(function (newName) {
          if (newName && newName.trim()) {
            renameOutfit(btn.dataset.outfitId, newName.trim());
            renderOutfitsPage();
          }
        });
      });
    });

    // Wire up delete buttons
    container.querySelectorAll('.btn-delete-outfit').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var board = btn.closest('.outfit-board');
        var nameEl = board ? board.querySelector('.outfit-board-name') : null;
        var name = nameEl ? nameEl.textContent : 'this outfit';
        showConfirm('Delete "' + name + '"?').then(function (ok) {
          if (ok) {
            deleteOutfit(btn.dataset.outfitId);
            renderOutfitsPage();
          }
        });
      });
    });

    // Wire up complete-outfit buttons (WN-101 implementation)
    container.querySelectorAll('.btn-complete-outfit').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var outfitId = btn.dataset.outfitId;
        var outfits = getOutfits();
        var outfit = null;
        outfits.forEach(function (o) { if (o.id === outfitId) outfit = o; });
        if (!outfit || !outfit.items.length) return;

        var suggestionsEl = document.getElementById('outfit-suggestions-' + outfitId);
        if (!suggestionsEl) return;

        btn.disabled = true;
        btn.textContent = 'Thinking…';

        var itemNames = outfit.items.map(function (i) { return {name: i.name}; });

        fetch('/outfits/complete', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({items: itemNames})
        })
          .then(function (res) { return res.json(); })
          .then(function (data) {
            btn.disabled = false;
            btn.textContent = 'Complete this outfit';
            if (!data.suggestions || !data.suggestions.length) {
              suggestionsEl.innerHTML = '<p class="outfit-suggestions-empty">No suggestions available.</p>';
              suggestionsEl.hidden = false;
              return;
            }
            var chipsHtml = '<p class="outfit-suggestions-label">Suggested items to complete this outfit:</p>'
              + '<ul class="outfit-suggestion-chips" aria-label="Outfit completion suggestions">';
            data.suggestions.forEach(function (s) {
              chipsHtml += '<li><a href="/search?q=' + encodeURIComponent(s) + '" class="example-chip">' + escapeHtml(s) + '</a></li>';
            });
            chipsHtml += '</ul>';
            suggestionsEl.innerHTML = chipsHtml;
            suggestionsEl.hidden = false;
          })
          .catch(function () {
            btn.disabled = false;
            btn.textContent = 'Complete this outfit';
            suggestionsEl.innerHTML = '<p class="outfit-suggestions-empty">Could not get suggestions. Please try again.</p>';
            suggestionsEl.hidden = false;
          });
      });
    });

    // Wire up "Shop all" buttons (WN-162)
    container.querySelectorAll('.btn-shop-all-outfit').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var outfitId = btn.dataset.outfitId;
        var outfits = getOutfits();
        var outfit = null;
        outfits.forEach(function (o) { if (o.id === outfitId) outfit = o; });
        if (!outfit || !outfit.items.length) return;
        var urls = outfit.items.map(function (i) { return i.url; }).filter(Boolean);
        if (!urls.length) return;
        if (urls.length > 5) {
          showConfirm('Open ' + urls.length + ' tabs for "' + outfit.name + '"?').then(function (ok) {
            if (ok) urls.forEach(function (url) { window.open(url, '_blank', 'noopener noreferrer'); });
          });
          return;
        }
        urls.forEach(function (url) { window.open(url, '_blank', 'noopener noreferrer'); });
      });
    });

    // Wire up try-on and style-it buttons on outfit items
    initTryOnButtons();
    if (typeof window.initStyleItButtons === 'function') window.initStyleItButtons();

    // Wire up share buttons (WN-102 implementation)
    container.querySelectorAll('.btn-share-outfit').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var outfitId = btn.dataset.outfitId;
        var outfits = getOutfits();
        var outfit = null;
        outfits.forEach(function (o) { if (o.id === outfitId) outfit = o; });
        if (!outfit) return;

        try {
          var encoded = btoa(JSON.stringify({name: outfit.name, items: outfit.items}));
          var shareUrl = window.location.origin + '/outfits#v1:' + encoded;
          if (navigator.clipboard) {
            navigator.clipboard.writeText(shareUrl).then(function () {
              var orig = btn.textContent;
              btn.textContent = 'Link copied!';
              btn.classList.add('is-copied');
              setTimeout(function () {
                btn.textContent = orig;
                btn.classList.remove('is-copied');
              }, 2000);
            });
          } else {
            showDialog('Copy this link:', shareUrl);
          }
        } catch (e) {
          showDialog('Could not copy automatically. Share this link:', shareUrl);
        }
      });
    });
  }

  // ------------------------------------------------------------------ //
  // Canvas saves section on outfits page (WN-148)                      //
  // ------------------------------------------------------------------ //
  var CANVAS_SAVES_KEY = 'cloth_canvas_saves';

  function _getCanvasSaves() {
    try { return JSON.parse(localStorage.getItem(CANVAS_SAVES_KEY) || '[]'); } catch (e) { return []; }
  }
  function _setCanvasSaves(saves) {
    try { localStorage.setItem(CANVAS_SAVES_KEY, JSON.stringify(saves)); } catch (e) { /* ignore */ }
  }

  function renderCanvasSaves() {
    var container = document.getElementById('canvas-saves-container');
    if (!container) return;
    var saves = _getCanvasSaves();
    if (!saves.length) {
      container.innerHTML = '<p class="canvas-saves-empty">No saved canvases yet. Build a canvas in the style tool and click "Save canvas".</p>';
      return;
    }
    var html = '<ul class="canvas-saves-list" aria-label="Saved canvases">';
    saves.forEach(function (save) {
      var date = '';
      try { date = new Date(save.savedAt).toLocaleDateString(); } catch (e) { /* ignore */ }
      var thumbHtml = save.thumbnail
        ? '<img class="canvas-save-thumb" src="' + escapeHtml(save.thumbnail) + '" alt="' + escapeHtml(save.name) + ' preview">'
        : '<div class="canvas-save-thumb-placeholder" aria-hidden="true"></div>';
      html += '<li class="canvas-save-card">'
        + thumbHtml
        + '<p class="canvas-save-name">' + escapeHtml(save.name) + '</p>'
        + '<p class="canvas-save-date">' + escapeHtml(date) + '</p>'
        + '<button class="btn-open-canvas-save btn-secondary" data-save-id="' + escapeHtml(save.id) + '" aria-label="Open ' + escapeHtml(save.name) + '">Open</button>'
        + '<button class="btn-delete-canvas-save" data-save-id="' + escapeHtml(save.id) + '" aria-label="Delete ' + escapeHtml(save.name) + '">Remove</button>'
        + '</li>';
    });
    html += '</ul>';
    container.innerHTML = html;

    container.querySelectorAll('.btn-open-canvas-save').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.dataset.saveId;
        var saves = _getCanvasSaves();
        var save = null;
        for (var i = 0; i < saves.length; i++) { if (saves[i].id === id) { save = saves[i]; break; } }
        if (save && typeof window.loadCanvasSave === 'function') window.loadCanvasSave(save);
      });
    });

    container.querySelectorAll('.btn-delete-canvas-save').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.dataset.saveId;
        var saves = _getCanvasSaves().filter(function (s) { return s.id !== id; });
        _setCanvasSaves(saves);
        renderCanvasSaves();
      });
    });
  }

  // Expose so style-canvas.js can call it after saving
  window.renderCanvasSaves = renderCanvasSaves;

  function initOutfitsPage() {
    var newBtn = document.getElementById('new-outfit-btn');
    if (!newBtn) return;

    newBtn.addEventListener('click', function () {
      showDialog('Outfit board name:', 'My outfit').then(function (name) {
        if (name && name.trim()) {
          createOutfit(name.trim());
          renderOutfitsPage();
        }
      });
    });

    // Handle shared outfit fragment (WN-102)
    var fragment = window.location.hash;
    if (fragment && fragment.indexOf('#v1:') === 0) {
      var encoded = fragment.slice(4);
      try {
        var shared = JSON.parse(atob(encoded));
        renderSharedOutfit(shared);
      } catch (e) {
        // invalid fragment — ignore
      }
    }

    renderOutfitsPage();
    renderCanvasSaves();
  }

  function renderSharedOutfit(shared) {
    var container = document.getElementById('outfits-container');
    if (!container) return;

    var itemsHtml = '';
    if (shared.items && shared.items.length) {
      itemsHtml = '<ul class="outfit-mini-grid" aria-label="Shared outfit items">';
      shared.items.forEach(function (item) {
        var imgHtml = item.image
          ? '<img src="' + escapeHtml(item.image) + '" alt="' + escapeHtml(item.name) + '" loading="lazy">'
          : '<div class="outfit-item-fallback">' + escapeHtml(item.retailer || '') + '</div>';
        itemsHtml += '<li class="outfit-mini-item">'
          + '<div class="outfit-mini-image">' + imgHtml + '</div>'
          + '<p class="outfit-mini-name">' + escapeHtml(item.name) + '</p>'
          + '<p class="outfit-mini-price">' + escapeHtml(item.price || '') + '</p>'
          + (item.url ? '<a href="' + escapeHtml(item.url) + '" class="btn-view" rel="noopener noreferrer" target="_blank">View item</a>' : '')
          + '<button class="btn-save-shared-item btn-save"'
          + ' data-id="' + escapeHtml(item.id || generateId()) + '"'
          + ' data-name="' + escapeHtml(item.name) + '"'
          + ' data-price="' + escapeHtml(item.price || '') + '"'
          + ' data-retailer="' + escapeHtml(item.retailer || '') + '"'
          + ' data-image="' + escapeHtml(item.image || '') + '"'
          + ' data-url="' + escapeHtml(item.url || '') + '"'
          + ' aria-label="Save ' + escapeHtml(item.name) + '"'
          + ' aria-pressed="false">&#9825; Save</button>'
          + '</li>';
      });
      itemsHtml += '</ul>';
    }

    var sharedPanel = document.createElement('div');
    sharedPanel.className = 'shared-outfit-panel';
    sharedPanel.setAttribute('aria-label', 'Shared outfit');
    sharedPanel.innerHTML = '<div class="shared-outfit-header">'
      + '<span class="shared-outfit-badge">Shared outfit</span>'
      + '<h2>' + escapeHtml(shared.name || 'Outfit') + '</h2>'
      + '</div>'
      + itemsHtml;

    container.insertBefore(sharedPanel, container.firstChild);
    initSaveButtons();
  }

  // ------------------------------------------------------------------ //
  // Add to outfit picker (WN-100)                                       //
  // ------------------------------------------------------------------ //

  function showOutfitPicker(btn, itemData) {
    // Remove any existing picker
    var existing = document.querySelector('.outfit-picker');
    if (existing) existing.remove();

    var outfits = getOutfits();

    var picker = document.createElement('div');
    picker.className = 'outfit-picker';
    picker.setAttribute('role', 'dialog');
    picker.setAttribute('aria-label', 'Add to outfit');

    var title = document.createElement('p');
    title.className = 'outfit-picker-title';
    title.textContent = 'Add to outfit:';
    picker.appendChild(title);

    if (outfits.length) {
      var ul = document.createElement('ul');
      ul.className = 'outfit-picker-list';
      outfits.forEach(function (outfit) {
        var inOutfit = outfit.items.some(function (i) { return i.id === itemData.id; });
        var li = document.createElement('li');
        var optBtn = document.createElement('button');
        optBtn.className = 'outfit-picker-option' + (inOutfit ? ' is-in-outfit' : '');
        optBtn.textContent = outfit.name + (inOutfit ? ' ✓' : '');
        optBtn.setAttribute('aria-pressed', inOutfit ? 'true' : 'false');
        (function (o, alreadyIn) {
          optBtn.addEventListener('click', function () {
            if (!alreadyIn) {
              addItemToOutfit(o.id, itemData);
              optBtn.textContent = o.name + ' ✓';
              optBtn.classList.add('is-in-outfit');
              optBtn.setAttribute('aria-pressed', 'true');
              showToast('Added to "' + o.name + '"');
            }
            picker.remove();
          });
        }(outfit, inOutfit));
        li.appendChild(optBtn);
        ul.appendChild(li);
      });
      picker.appendChild(ul);
    }

    var newBtn = document.createElement('button');
    newBtn.className = 'outfit-picker-new';
    newBtn.textContent = '+ New outfit';
    newBtn.addEventListener('click', function () {
      picker.remove();
      showDialog('Outfit board name:', 'My outfit').then(function (name) {
        if (name && name.trim()) {
          var newOutfit = createOutfit(name.trim());
          addItemToOutfit(newOutfit.id, itemData);
          showToast('Added to "' + newOutfit.name + '"');
          updateOutfitsCount();
        }
      });
    });
    picker.appendChild(newBtn);

    var closeBtn = document.createElement('button');
    closeBtn.className = 'outfit-picker-close';
    closeBtn.textContent = 'Cancel';
    closeBtn.setAttribute('aria-label', 'Close outfit picker');
    closeBtn.addEventListener('click', function () { picker.remove(); });
    picker.appendChild(closeBtn);

    // Position near button
    btn.parentNode.style.position = 'relative';
    btn.parentNode.appendChild(picker);

    // Close on outside click
    function onOutsideClick(e) {
      if (!picker.contains(e.target) && e.target !== btn) {
        picker.remove();
        document.removeEventListener('click', onOutsideClick, true);
      }
    }
    setTimeout(function () {
      document.addEventListener('click', onOutsideClick, true);
    }, 0);
  }

  function showToast(message) {
    var existing = document.querySelector('.cloth-toast');
    if (existing) existing.remove();

    var toast = document.createElement('div');
    toast.className = 'cloth-toast';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(function () { toast.remove(); }, 2500);
  }

  // Expose so style-canvas.js can call it
  window.showToast = showToast;

  function initAddToOutfitButtons() {
    document.querySelectorAll('.btn-add-to-outfit').forEach(function (btn) {
      if (btn.dataset.outfitBound) return;
      btn.dataset.outfitBound = '1';
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        showOutfitPicker(btn, {
          id: btn.dataset.id,
          name: btn.dataset.name,
          price: btn.dataset.price,
          retailer: btn.dataset.retailer,
          image: btn.dataset.image,
          url: btn.dataset.url
        });
      });
    });
  }

  var deriveSimilarQuery = window.ClothPure.deriveSimilarQuery;

  var DENSITY_KEY = 'cloth_density';

  function _initQueryAugmentChips(selector, dataAttr) {
    var resultsHeader = document.querySelector('.results-header[data-query]');
    if (!resultsHeader) return;
    var baseQuery = resultsHeader.dataset.query || '';

    document.querySelectorAll(selector).forEach(function (btn) {
      if (btn.dataset.augBound) return;
      btn.dataset.augBound = '1';
      btn.addEventListener('click', function () {
        var isActive = btn.getAttribute('aria-pressed') === 'true';
        document.querySelectorAll(selector).forEach(function (b) {
          b.setAttribute('aria-pressed', 'false');
          b.classList.remove('active');
        });
        if (!isActive) {
          btn.setAttribute('aria-pressed', 'true');
          btn.classList.add('active');
          var term = btn.dataset[dataAttr];
          doAjaxSearch((baseQuery + ' ' + term).trim(), null, false, true);
        } else {
          doAjaxSearch(baseQuery.trim(), null, false, true);
        }
      });
    });
  }

  var _lmObserver = null;

  function _doLoadMore(query, nextStart, wrap, onDone) {
    var url = '/search?q=' + encodeURIComponent(query) + '&format=json&start=' + nextStart;
    fetch(url)
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (!data.products || !data.products.length) {
          if (wrap) wrap.remove();
          if (onDone) onDone(false, nextStart);
          return;
        }
        var grid = document.getElementById('product-grid');
        if (!grid) { if (onDone) onDone(false, nextStart); return; }
        var tmp = document.createElement('ul');
        tmp.innerHTML = data.cards_html || '';
        while (tmp.firstElementChild) { grid.appendChild(tmp.firstElementChild); }
        initSaveButtons();
        initCopyLinkButtons();
        initAddToOutfitButtons();
        initTryOnButtons();
        if (typeof window.initStyleItButtons === 'function') window.initStyleItButtons();
        initRecentlyViewedTracking();
        updateSavedCount();
        if (onDone) onDone(data.has_more, nextStart + 10);
        if (!data.has_more && wrap) wrap.remove();
      })
      .catch(function () {
        if (onDone) onDone(false, nextStart);
      });
  }

  function initLoadMore() {
    // Disconnect any previous observer
    if (_lmObserver) { _lmObserver.disconnect(); _lmObserver = null; }

    var wrap = document.getElementById('load-more-wrap');
    var btn = document.getElementById('btn-load-more');
    if (!btn || btn.dataset.lmBound) return;
    btn.dataset.lmBound = '1';

    var query = btn.dataset.query;
    var nextStart = parseInt(btn.dataset.nextStart, 10) || 10;

    // IntersectionObserver path — auto load-more (WN-151)
    if ('IntersectionObserver' in window) {
      // Replace visible button with a sentinel spinner
      var sentinel = document.createElement('div');
      sentinel.id = 'lm-sentinel';
      sentinel.className = 'lm-sentinel';
      sentinel.setAttribute('aria-hidden', 'true');
      if (wrap) {
        btn.style.display = 'none'; // keep as fallback but hidden
        wrap.appendChild(sentinel);
      }

      var _loading = false;
      _lmObserver = new IntersectionObserver(function (entries) {
        if (!entries[0].isIntersecting || _loading) return;
        _loading = true;
        sentinel.classList.add('is-loading');
        _doLoadMore(query, nextStart, wrap, function (hasMore, newStart) {
          _loading = false;
          nextStart = newStart;
          sentinel.classList.remove('is-loading');
          if (!hasMore) {
            _lmObserver.disconnect();
            _lmObserver = null;
            sentinel.remove();
          }
        });
      }, {rootMargin: '300px'});
      _lmObserver.observe(sentinel);
      return;
    }

    // Fallback: click button (browsers without IntersectionObserver)
    btn.addEventListener('click', function () {
      btn.disabled = true;
      btn.textContent = 'Loading…';
      _doLoadMore(query, nextStart, wrap, function (hasMore, newStart) {
        nextStart = newStart;
        if (hasMore) {
          btn.disabled = false;
          btn.textContent = 'Load more results';
        }
      });
    });
  }

  function initPriceSlider() {
    var grid = document.getElementById('product-grid');
    var sliderGroup = document.getElementById('price-slider-group');
    var sliderMin = document.getElementById('price-range-min');
    var sliderMax = document.getElementById('price-range-max');
    var display = document.getElementById('price-slider-display');
    if (!grid || !sliderGroup || !sliderMin || !sliderMax || !display) return;

    var prices = Array.prototype.slice.call(grid.querySelectorAll('.product-card'))
      .map(function (c) { return parseFloat(c.dataset.priceValue); })
      .filter(function (v) { return !isNaN(v); });

    if (!prices.length) return;

    var dataMin = Math.floor(Math.min.apply(null, prices));
    var dataMax = Math.ceil(Math.max.apply(null, prices));
    if (dataMin === dataMax) return;

    sliderMin.min = dataMin;
    sliderMin.max = dataMax;
    sliderMin.value = dataMin;
    sliderMax.min = dataMin;
    sliderMax.max = dataMax;
    sliderMax.value = dataMax;
    display.textContent = '£' + dataMin + ' – £' + dataMax;
    sliderGroup.style.display = '';

    function updateDisplay() {
      var lo = Math.min(parseInt(sliderMin.value, 10), parseInt(sliderMax.value, 10));
      var hi = Math.max(parseInt(sliderMin.value, 10), parseInt(sliderMax.value, 10));
      display.textContent = '£' + lo + ' – £' + hi;
    }

    function onSliderInput() {
      var lo = parseInt(sliderMin.value, 10);
      var hi = parseInt(sliderMax.value, 10);
      if (lo > hi) {
        if (this === sliderMin) { sliderMin.value = hi; }
        else { sliderMax.value = lo; }
      }
      updateDisplay();
      document.querySelectorAll('.filter-chip:not(.retailer-chip)').forEach(function (c) {
        c.classList.remove('active');
        c.setAttribute('aria-pressed', 'false');
      });
      applyFilterSort();
    }

    var debouncedSlider = _debounce(onSliderInput.bind(sliderMin), 200);
    sliderMin.addEventListener('input', debouncedSlider);
    sliderMax.addEventListener('input', debouncedSlider);
  }

  function initGenderFilter() {
    _initQueryAugmentChips('.gender-chip', 'gender');
  }

  function initCategoryFilter() {
    _initQueryAugmentChips('.category-chip', 'category');
  }

  function initColorFilter() {
    _initQueryAugmentChips('.color-chip', 'color');
  }

  function initSizeFilter() {
    _initQueryAugmentChips('.size-chip', 'size');
  }

  function initDensityToggle() {
    var grid = document.getElementById('product-grid');
    if (!grid) return;

    var saved = localStorage.getItem(DENSITY_KEY) || 'comfortable';
    grid.dataset.density = saved;

    document.querySelectorAll('.density-btn').forEach(function (btn) {
      if (btn.dataset.density === saved) btn.classList.add('is-active');
      btn.addEventListener('click', function () {
        var d = btn.dataset.density;
        grid.dataset.density = d;
        localStorage.setItem(DENSITY_KEY, d);
        document.querySelectorAll('.density-btn').forEach(function (b) {
          b.classList.toggle('is-active', b.dataset.density === d);
        });
      });
    });
  }

  // ------------------------------------------------------------------ //
  // Virtual try-on modal (WN-106/WN-107)                               //
  // ------------------------------------------------------------------ //
  var _TRY_ON_ENABLED = false;

  function _initTryOnEnabled() {
    var meta = document.querySelector('meta[name="try-on-enabled"]');
    _TRY_ON_ENABLED = !!(meta && meta.getAttribute('content') === 'true');
  }

  function openTryOnModal(garmentUrl, garmentName) {
    var existing = document.getElementById('try-on-modal');
    if (existing) existing.remove();

    var modal = document.createElement('div');
    modal.id = 'try-on-modal';
    modal.className = 'try-on-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-label', 'Virtual try-on: ' + escapeHtml(garmentName));

    modal.innerHTML = '<div class="try-on-modal-inner">'
      + '<button type="button" class="try-on-close" aria-label="Close try-on">×</button>'
      + '<h2 class="try-on-heading">Try on: ' + escapeHtml(garmentName) + '</h2>'
      + '<div class="try-on-upload">'
      + '<label for="try-on-file" class="try-on-file-label">Upload your photo (JPEG or PNG, max 5 MB)</label>'
      + '<input type="file" id="try-on-file" accept="image/jpeg,image/png" class="try-on-file">'
      + '<div id="try-on-preview" class="try-on-preview" hidden></div>'
      + '</div>'
      + '<div class="try-on-consent">'
      + '<label class="try-on-consent-label">'
      + '<input type="checkbox" id="try-on-consent-check">'
      + ' Your photo is processed to generate the result and is not stored or shared.'
      + ' <a href="/privacy" target="_blank" rel="noopener noreferrer">Privacy Notice</a>'
      + '</label>'
      + '</div>'
      + '<div class="try-on-category">'
      + '<label for="try-on-category-select">Garment type:</label>'
      + '<select id="try-on-category-select" class="try-on-category-select">'
      + '<option value="">Auto-detect</option>'
      + '<option value="tops">Tops</option>'
      + '<option value="bottoms">Bottoms</option>'
      + '<option value="one-piece">One-piece / Dress</option>'
      + '</select>'
      + '</div>'
      + '<button type="button" id="try-on-generate" class="btn-primary try-on-generate" disabled>Generate try-on</button>'
      + '<div id="try-on-loading" class="try-on-loading" hidden>'
      + '<span class="try-on-spinner" aria-hidden="true"></span>'
      + '<p>This may take up to 30 seconds…</p>'
      + '</div>'
      + '<div id="try-on-result" class="try-on-result" hidden>'
      + '<img id="try-on-result-img" alt="Try-on result">'
      + '<div class="try-on-result-actions">'
      + '<button type="button" id="try-on-save" class="btn-secondary">Save result</button>'
      + '<button type="button" id="try-on-another" class="btn-secondary">Try another item</button>'
      + '</div>'
      + '</div>'
      + '<div id="try-on-error" class="try-on-error" role="alert" hidden></div>'
      + '</div>';

    document.body.appendChild(modal);

    var fileInput = modal.querySelector('#try-on-file');
    var consentCheck = modal.querySelector('#try-on-consent-check');
    var generateBtn = modal.querySelector('#try-on-generate');
    var closeBtn = modal.querySelector('.try-on-close');

    closeBtn.focus();

    function updateGenerateBtn() {
      generateBtn.disabled = !(fileInput.files && fileInput.files[0] && consentCheck.checked);
    }

    fileInput.addEventListener('change', function () {
      updateGenerateBtn();
      var previewEl = modal.querySelector('#try-on-preview');
      if (fileInput.files && fileInput.files[0]) {
        var reader = new FileReader();
        reader.onload = function (e) {
          previewEl.innerHTML = '<img src="' + escapeHtml(e.target.result) + '" alt="Your photo preview">';
          previewEl.hidden = false;
        };
        reader.readAsDataURL(fileInput.files[0]);
      } else {
        previewEl.hidden = true;
        previewEl.innerHTML = '';
      }
    });

    consentCheck.addEventListener('change', updateGenerateBtn);

    generateBtn.addEventListener('click', function () {
      if (!fileInput.files || !fileInput.files[0]) return;
      modal.querySelector('#try-on-loading').hidden = false;
      modal.querySelector('#try-on-result').hidden = true;
      modal.querySelector('#try-on-error').hidden = true;
      generateBtn.disabled = true;

      var categorySelect = modal.querySelector('#try-on-category-select');
      var formData = new FormData();
      formData.append('person_image', fileInput.files[0]);
      formData.append('garment_url', garmentUrl);
      formData.append('garment_name', garmentName || '');
      if (categorySelect && categorySelect.value) {
        formData.append('category_override', categorySelect.value);
      }

      fetch('/try-on', {method: 'POST', body: formData})
        .then(function (res) { return res.json(); })
        .then(function (data) {
          modal.querySelector('#try-on-loading').hidden = true;
          if (data.result_url) {
            var resultImg = modal.querySelector('#try-on-result-img');
            resultImg.src = data.result_url;
            modal.querySelector('#try-on-result').hidden = false;
          } else {
            var errEl = modal.querySelector('#try-on-error');
            errEl.textContent = data.error || 'Try-on failed. Please try again.';
            errEl.hidden = false;
            updateGenerateBtn();
          }
        })
        .catch(function () {
          modal.querySelector('#try-on-loading').hidden = true;
          var errEl = modal.querySelector('#try-on-error');
          errEl.textContent = 'Could not connect to try-on service. Please try again.';
          errEl.hidden = false;
          updateGenerateBtn();
        });
    });

    modal.querySelector('#try-on-save').addEventListener('click', function () {
      var img = modal.querySelector('#try-on-result-img');
      if (!img || !img.src) return;
      var a = document.createElement('a');
      a.href = img.src;
      a.download = 'try-on-result.jpg';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    });

    modal.querySelector('#try-on-another').addEventListener('click', function () {
      modal.querySelector('#try-on-result').hidden = true;
      modal.querySelector('#try-on-error').hidden = true;
      fileInput.value = '';
      var previewEl = modal.querySelector('#try-on-preview');
      previewEl.hidden = true;
      previewEl.innerHTML = '';
      consentCheck.checked = false;
      updateGenerateBtn();
      fileInput.focus();
    });

    function closeModal() {
      modal.remove();
      document.removeEventListener('keydown', onKeyDown);
    }

    closeBtn.addEventListener('click', closeModal);

    modal.addEventListener('click', function (e) {
      if (e.target === modal) closeModal();
    });

    function onKeyDown(e) {
      if (e.key === 'Escape') {
        closeModal();
        return;
      }
      if (e.key === 'Tab') {
        var focusable = Array.prototype.slice.call(
          modal.querySelectorAll('button:not([disabled]), input, a[href]')
        );
        if (!focusable.length) return;
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    document.addEventListener('keydown', onKeyDown);
  }

  function initTryOnButtons() {
    document.querySelectorAll('.btn-try-on').forEach(function (btn) {
      if (btn.dataset.tryOnBound) return;
      btn.dataset.tryOnBound = '1';
      if (!_TRY_ON_ENABLED) {
        btn.style.display = 'none';
        return;
      }
      btn.addEventListener('click', function () {
        openTryOnModal(btn.dataset.garmentUrl || '', btn.dataset.garmentName || '');
      });
    });
  }

  var _COMPARE_KEY = 'cloth_compare';
  var _COMPARE_MAX = 4;

  function _getCompareItems() {
    try {
      var raw = localStorage.getItem(_COMPARE_KEY);
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function _saveCompareItems(items) {
    try {
      localStorage.setItem(_COMPARE_KEY, JSON.stringify(items));
    } catch (e) { /* storage full or unavailable */ }
  }

  function _renderCompareBar() {
    var bar = document.getElementById('compare-bar');
    if (!bar) return;
    var items = _getCompareItems();
    if (items.length < 2) {
      bar.hidden = true;
      return;
    }
    bar.hidden = false;
    var container = document.getElementById('compare-items');
    if (!container) return;

    var html = '';
    items.forEach(function (item) {
      html += '<div class="compare-item">'
        + (item.image ? '<img src="' + escapeHtml(item.image) + '" alt="' + escapeHtml(item.name) + '" class="compare-item-img">' : '')
        + '<div class="compare-item-info">'
        + '<span class="compare-item-name">' + escapeHtml(item.name) + '</span>'
        + (item.price ? '<span class="compare-item-price">' + escapeHtml(item.price) + '</span>' : '')
        + '<span class="compare-item-retailer">' + escapeHtml(item.retailer) + '</span>'
        + '</div>'
        + '<a href="' + escapeHtml(item.url) + '" class="compare-item-link btn-view" target="_blank" rel="noopener noreferrer" aria-label="View ' + escapeHtml(item.name) + '">View</a>'
        + '<button type="button" class="compare-item-remove" data-compare-id="' + escapeHtml(item.id) + '" aria-label="Remove ' + escapeHtml(item.name) + ' from comparison">&times;</button>'
        + '</div>';
    });
    container.innerHTML = html;

    container.querySelectorAll('.compare-item-remove').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.dataset.compareId;
        var updated = _getCompareItems().filter(function (i) { return i.id !== id; });
        _saveCompareItems(updated);
        _renderCompareBar();
        _syncCompareButtons();
      });
    });
  }

  function _syncCompareButtons() {
    var items = _getCompareItems();
    var ids = items.map(function (i) { return i.id; });
    document.querySelectorAll('.btn-compare').forEach(function (btn) {
      var active = ids.indexOf(btn.dataset.id) !== -1;
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      btn.classList.toggle('is-comparing', active);
    });
  }

  function initCompare() {
    _renderCompareBar();
    _syncCompareButtons();

    var clearBtn = document.getElementById('compare-clear');
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        _saveCompareItems([]);
        _renderCompareBar();
        _syncCompareButtons();
      });
    }

    if (!window._compareClickBound) {
      window._compareClickBound = true;
      document.addEventListener('click', function (e) {
        var btn = e.target.closest('.btn-compare');
        if (!btn) return;
      var id = btn.dataset.id;
      if (!id) return;

      var items = _getCompareItems();
      var existing = items.findIndex(function (i) { return i.id === id; });

      if (existing !== -1) {
        items.splice(existing, 1);
      } else {
        if (items.length >= _COMPARE_MAX) return;
        items.push({
          id: id,
          name: btn.dataset.name || '',
          price: btn.dataset.price || '',
          retailer: btn.dataset.retailer || '',
          image: btn.dataset.image || '',
          url: btn.dataset.url || ''
        });
      }
      _saveCompareItems(items);
      _renderCompareBar();
      _syncCompareButtons();
      });
    }
  }

  function initRefineBar() {
    var bar = document.getElementById('refine-bar');
    if (!bar) return;
    var input = document.getElementById('refine-input');
    var btn = document.getElementById('refine-btn');
    var status = document.getElementById('refine-status');
    if (!input || !btn) return;

    function doRefine() {
      var refinement = input.value.trim();
      if (!refinement) return;
      var resultsHeader = document.querySelector('.results-header[data-query]');
      var originalQuery = resultsHeader ? resultsHeader.dataset.query : '';
      if (!originalQuery) return;

      btn.disabled = true;
      status.textContent = 'Refining…';

      fetch('/search/refine', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({original_query: originalQuery, refinement: refinement})
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          btn.disabled = false;
          status.textContent = '';
          if (data.new_query) {
            doAjaxSearch(data.new_query, null);
          }
        })
        .catch(function () {
          btn.disabled = false;
          status.textContent = 'Refinement failed. Please try again.';
        });
    }

    btn.addEventListener('click', doRefine);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') doRefine();
    });
  }

  // ------------------------------------------------------------------ //
  // SPA navigation (WN-145/146)                                        //
  // ------------------------------------------------------------------ //
  var _navController = null;

  function navigateTo(url, push) {
    _cancelPhase2();
    if (_navController) { _navController.abort(); _navController = null; }
    _navController = new AbortController();

    if (push !== false) {
      history.pushState({url: url, type: 'nav'}, '', url);
    }

    document.documentElement.classList.add('is-navigating');

    return fetch(url, {signal: _navController.signal})
      .then(function (res) { return res.text(); })
      .then(function (html) {
        _navController = null;
        var mainMatch = html.match(/<main[^>]*>([\s\S]*?)<\/main>/i);
        var curMain = document.querySelector('main');
        if (mainMatch && curMain) {
          curMain.innerHTML = mainMatch[1];
        }
        var titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
        if (titleMatch) {
          document.title = titleMatch[1].replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
        }
        document.documentElement.classList.remove('is-navigating');
        window.scrollTo(0, 0);
        initPage();
      })
      .catch(function (err) {
        _navController = null;
        document.documentElement.classList.remove('is-navigating');
        if (err.name !== 'AbortError') {
          window.location.href = url;
        }
      });
  }

  function _initSpaNavigation() {
    if (window._spaNavBound) return;
    window._spaNavBound = true;

    // Intercept same-origin link clicks for SPA navigation
    document.addEventListener('click', function (e) {
      var link = e.target.closest('a[href]');
      if (!link) return;
      if (link.target && link.target !== '_self') return;
      try { if (new URL(link.href).origin !== window.location.origin) return; }
      catch (err) { return; }
      var href = link.getAttribute('href');
      if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0) return;
      if (link.hasAttribute('download')) return;

      var url = link.href;
      var urlObj = new URL(url);
      var q = urlObj.searchParams.get('q');

      // Search links → AJAX search (two-phase)
      if (urlObj.pathname === '/search' && q) {
        e.preventDefault();
        history.pushState({query: q, type: 'search'}, '', url);
        doAjaxSearch(q, null);
        return;
      }

      // Other internal links → SPA page swap (skip format=json links used internally)
      if (urlObj.searchParams.get('format') === 'json') return;
      e.preventDefault();
      navigateTo(url);
    });

    // Browser back/forward
    window.addEventListener('popstate', function (e) {
      var state = e.state;
      if (!state) { window.location.reload(); return; }
      if (state.query) {
        doAjaxSearch(state.query, null);
      } else if (state.url) {
        navigateTo(state.url, false);
      } else {
        window.location.reload();
      }
    });
  }

  // Per-page init — safe to call after every SPA navigation
  function initPage() {
    document.querySelectorAll('.product-image-wrap img').forEach(function (img) {
      if (img._fallbackBound) return;
      img._fallbackBound = true;
      img.addEventListener('error', function () {
        img.style.display = 'none';
        var fallback = img.nextElementSibling;
        if (fallback && fallback.classList.contains('image-fallback')) {
          fallback.style.display = 'flex';
        }
      });
      if (img.complete && !img.naturalWidth) img.dispatchEvent(new Event('error'));
    });

    _initTryOnEnabled();
    initSearchLoadingFeedback();
    initFilterSort();
    initColorFilter();
    initGenderFilter();
    initCategoryFilter();
    initSizeFilter();
    initDensityToggle();
    initLoadMore();
    initAjaxSearch();

    var resultsHeader = document.querySelector('.results-header[data-query]');
    if (resultsHeader && resultsHeader.dataset.query) {
      saveSearchToHistory(resultsHeader.dataset.query);
    }

    renderSearchHistory();
    renderRecentlyViewed();
    initRecentlyViewedTracking();
    initSaveButtons();
    initCopyLinkButtons();
    updateSavedCount();

    if (document.getElementById('saved-items-container')) {
      initCollections();
      initShareSavedList();
    }

    if (document.getElementById('outfits-container')) {
      initOutfitsPage();
    }

    initAddToOutfitButtons();
    updateOutfitsCount();
    initTryOnButtons();
    initRefineBar();
    initCompare();
    _syncCompareButtons();
    if (typeof window.initStyleItButtons === 'function') window.initStyleItButtons();
    initStickyFilterBar();
    initMobileFilterToggle();

    // One-time document-level setup
    _initSpaNavigation();
  }

  // ------------------------------------------------------------------ //
  // Image lightbox (WN-156)                                             //
  // ------------------------------------------------------------------ //
  function _initLightbox() {
    if (window._lightboxBound) return;
    window._lightboxBound = true;

    var lightbox = document.getElementById('img-lightbox');
    var lbImg = document.getElementById('img-lightbox-img');
    if (!lightbox || !lbImg) return;

    function openLightbox(src, alt) {
      lbImg.src = src;
      lbImg.alt = alt || '';
      lightbox.style.display = '';
      var closeBtn = lightbox.querySelector('.img-lightbox-close');
      if (closeBtn) closeBtn.focus();
      document.body.style.overflow = 'hidden';
    }

    function closeLightbox() {
      lightbox.style.display = 'none';
      lbImg.src = '';
      document.body.style.overflow = '';
    }

    var closeBtn = lightbox.querySelector('.img-lightbox-close');
    if (closeBtn) closeBtn.addEventListener('click', closeLightbox);

    var backdrop = lightbox.querySelector('.img-lightbox-backdrop');
    if (backdrop) backdrop.addEventListener('click', closeLightbox);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && lightbox.style.display !== 'none') {
        closeLightbox();
      }
    });

    // Delegate click on product images to open lightbox
    document.addEventListener('click', function (e) {
      var wrap = e.target.closest('.product-image-wrap');
      if (!wrap) return;
      var img = wrap.querySelector('img');
      if (!img || !img.src) return;
      openLightbox(img.src, img.alt);
    });
  }

  function initImageLightbox() {
    _initLightbox();
    // Re-bind click on any new product images — lightbox uses delegation, nothing extra needed
  }

  // WN-120: mobile filter bar collapse
  function initMobileFilterToggle() {
    var bar = document.getElementById('filter-sort-bar');
    if (!bar || bar._mobileToggleBound) return;
    if (!window.matchMedia('(max-width: 768px)').matches) return;
    bar._mobileToggleBound = true;

    function countActiveFilters() {
      var active = 0;
      bar.querySelectorAll('.filter-chip[aria-pressed="true"]:not([data-min=""]), .filter-chip.active').forEach(function (el) {
        if (!(el.dataset.min === '' && el.dataset.max === '')) active++;
      });
      var keyword = bar.querySelector('#keyword-filter');
      if (keyword && keyword.value && keyword.value.trim()) active++;
      return active;
    }

    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.id = 'mobile-filter-toggle';
    toggle.className = 'mobile-filter-toggle';

    function updateToggleLabel() {
      var n = countActiveFilters();
      toggle.textContent = n > 0 ? 'Filters (' + n + ')' : 'Filters';
      toggle.setAttribute('aria-expanded', bar.classList.contains('is-expanded') ? 'true' : 'false');
    }

    var savedOpen = sessionStorage.getItem('cloth_filter_open') === '1';
    if (savedOpen) bar.classList.add('is-expanded');

    toggle.addEventListener('click', function () {
      var open = bar.classList.toggle('is-expanded');
      sessionStorage.setItem('cloth_filter_open', open ? '1' : '0');
      updateToggleLabel();
    });

    bar.insertBefore(toggle, bar.firstChild);
    updateToggleLabel();
  }

  // WN-152: sticky filter bar — set --header-h and detect stuck state
  function initStickyFilterBar() {
    var header = document.querySelector('.site-header');
    if (header) {
      document.documentElement.style.setProperty('--header-h', header.offsetHeight + 'px');
    }

    var bar = document.getElementById('filter-sort-bar');
    if (!bar || bar._stickyBound) return;
    bar._stickyBound = true;

    if ('IntersectionObserver' in window) {
      // Sentinel placed 1px above the bar's sticky position
      var sentinel = document.createElement('div');
      sentinel.style.cssText = 'position: absolute; top: -1px; height: 1px; width: 100%; pointer-events: none;';
      bar.parentNode.insertBefore(sentinel, bar);
      var obs = new IntersectionObserver(function (entries) {
        bar.classList.toggle('is-stuck', !entries[0].isIntersecting);
      }, {threshold: [0], rootMargin: '-' + (header ? header.offsetHeight : 0) + 'px 0px 0px 0px'});
      obs.observe(sentinel);
    }
  }

  // WN-158: back-to-top button
  function initBackToTop() {
    if (window._backToTopBound) return;
    window._backToTopBound = true;

    var btn = document.createElement('button');
    btn.id = 'back-to-top';
    btn.className = 'btn-back-to-top';
    btn.setAttribute('aria-label', 'Back to top');
    btn.textContent = '↑';
    btn.style.display = 'none';
    document.body.appendChild(btn);

    btn.addEventListener('click', function () {
      window.scrollTo({top: 0, behavior: 'smooth'});
    });

    window.addEventListener('scroll', function () {
      btn.style.display = window.scrollY > 400 ? '' : 'none';
    }, {passive: true});
  }

  // WN-157: mobile bottom navigation
  function initMobileNav() {
    if (window._mobileNavBound) return;
    window._mobileNavBound = true;

    var nav = document.querySelector('.mobile-bottom-nav');
    if (!nav) return;

    // Search tab focuses the header search input
    var searchTab = nav.querySelector('[data-nav="search"]');
    if (searchTab) {
      searchTab.addEventListener('click', function () {
        var input = document.querySelector('.header-search input[name="q"]');
        if (input) { input.focus(); input.select(); }
      });
    }

    // Set active tab based on current path
    var path = window.location.pathname;
    nav.querySelectorAll('.mobile-nav-tab[href]').forEach(function (tab) {
      var href = tab.getAttribute('href');
      var isActive = href === '/' ? path === '/' : path.startsWith(href);
      if (isActive) {
        tab.setAttribute('aria-current', 'page');
      } else {
        tab.removeAttribute('aria-current');
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    // One-time init that should not repeat on SPA page swaps
    initThemeToggle();
    initSearchAutocomplete();
    initImageLightbox(); // WN-156
    initMobileNav(); // WN-157
    initBackToTop(); // WN-158

    // Per-page init
    initPage();
  });
}());
