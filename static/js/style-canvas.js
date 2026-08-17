// Cloth — Style canvas (WN-112+)
(function () {
  'use strict';

  // ------------------------------------------------------------------ //
  // State                                                                //
  // ------------------------------------------------------------------ //
  var canvasLayers = []; // [{id, img, x, y, w, h, zIndex, label, placeholderColor}]
  var selectedLayerId = null;
  var baseImage = null; // HTMLImageElement for silhouette or uploaded photo
  var _nextLayerId = 1;
  var _triggerBtn = null; // element that opened the modal (restored on close)
  var _pendingOutfitItems = null; // outfit items to load as layers after base selection

  // Single-pointer drag state
  var _dragging = false;
  var _dragLayerId = null;
  var _dragOffsetX = 0;
  var _dragOffsetY = 0;

  // Corner-resize state
  var _resizing = false;
  var _resizeLayerId = null;
  var _resizeCorner = null; // 'tl' | 'tr' | 'bl' | 'br'
  var _resizeStartX = 0;
  var _resizeStartY = 0;
  var _resizeOrigLayer = null; // snapshot at resize start {x,y,w,h}

  // Pinch-to-resize state (WN-115)
  var _pinchActive = false;
  var _pinchPointers = {}; // pointerId -> {x, y}
  var _pinchLayerId = null;
  var _pinchStartDist = 0;
  var _pinchOrigW = 0;
  var _pinchOrigH = 0;

  var HANDLE_SIZE = 8;

  // ------------------------------------------------------------------ //
  // Helpers                                                              //
  // ------------------------------------------------------------------ //
  function _getCanvas() { return document.getElementById('style-canvas'); }
  function _getCtx() {
    var c = _getCanvas();
    return c ? c.getContext('2d') : null;
  }

  function _pointerPos(e) {
    var canvas = _getCanvas();
    var rect = canvas.getBoundingClientRect();
    var scaleX = canvas.width / rect.width;
    var scaleY = canvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY
    };
  }

  function _layerById(id) {
    for (var i = 0; i < canvasLayers.length; i++) {
      if (canvasLayers[i].id === id) return canvasLayers[i];
    }
    return null;
  }

  function _hitTestLayers(px, py) {
    var sorted = canvasLayers.slice().sort(function (a, b) { return b.zIndex - a.zIndex; });
    for (var i = 0; i < sorted.length; i++) {
      var l = sorted[i];
      if (px >= l.x && px <= l.x + l.w && py >= l.y && py <= l.y + l.h) return l.id;
    }
    return null;
  }

  function _hitTestCorner(layer, px, py) {
    var h = HANDLE_SIZE;
    var corners = {
      tl: { x: layer.x, y: layer.y },
      tr: { x: layer.x + layer.w, y: layer.y },
      bl: { x: layer.x, y: layer.y + layer.h },
      br: { x: layer.x + layer.w, y: layer.y + layer.h }
    };
    for (var k in corners) {
      if (!Object.prototype.hasOwnProperty.call(corners, k)) continue;
      var c = corners[k];
      if (Math.abs(px - c.x) <= h && Math.abs(py - c.y) <= h) return k;
    }
    return null;
  }

  function _randomColor() {
    var colors = ['#f0c0c0', '#c0f0c0', '#c0c0f0', '#f0e0c0', '#e0c0f0', '#c0f0f0'];
    return colors[Math.floor(Math.random() * colors.length)];
  }

  function _pinchDist() {
    var ids = Object.keys(_pinchPointers);
    if (ids.length < 2) return 0;
    var a = _pinchPointers[ids[0]];
    var b = _pinchPointers[ids[1]];
    var dx = a.x - b.x;
    var dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  // ------------------------------------------------------------------ //
  // Render                                                               //
  // ------------------------------------------------------------------ //
  function renderCanvas() {
    var canvas = _getCanvas();
    var ctx = _getCtx();
    if (!canvas || !ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw base image scaled to fit, centred
    if (baseImage) {
      var iw = baseImage.naturalWidth || baseImage.width;
      var ih = baseImage.naturalHeight || baseImage.height;
      if (iw && ih) {
        var scale = Math.min(canvas.width / iw, canvas.height / ih);
        var dx = (canvas.width - iw * scale) / 2;
        var dy = (canvas.height - ih * scale) / 2;
        ctx.drawImage(baseImage, dx, dy, iw * scale, ih * scale);
      }
    }

    // Draw layers in ascending z-order
    var sorted = canvasLayers.slice().sort(function (a, b) { return a.zIndex - b.zIndex; });
    sorted.forEach(function (layer) {
      if (layer.img) {
        ctx.drawImage(layer.img, layer.x, layer.y, layer.w, layer.h);
      } else {
        ctx.fillStyle = layer.placeholderColor || '#cccccc';
        ctx.fillRect(layer.x, layer.y, layer.w, layer.h);
        ctx.fillStyle = '#333333';
        ctx.font = '11px system-ui, sans-serif';
        ctx.fillText(layer.label || 'Loading…', layer.x + 4, layer.y + 14);
      }

      // Selection indicator + corner handles
      if (layer.id === selectedLayerId) {
        ctx.save();
        ctx.strokeStyle = '#3a55e0';
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 3]);
        ctx.strokeRect(layer.x, layer.y, layer.w, layer.h);
        ctx.setLineDash([]);
        ctx.restore();

        var h = HANDLE_SIZE;
        [
          { x: layer.x, y: layer.y },
          { x: layer.x + layer.w, y: layer.y },
          { x: layer.x, y: layer.y + layer.h },
          { x: layer.x + layer.w, y: layer.y + layer.h }
        ].forEach(function (corner) {
          ctx.fillStyle = '#ffffff';
          ctx.fillRect(corner.x - h / 2, corner.y - h / 2, h, h);
          ctx.strokeStyle = '#3a55e0';
          ctx.lineWidth = 1;
          ctx.strokeRect(corner.x - h / 2, corner.y - h / 2, h, h);
        });
      }
    });
  }

  // ------------------------------------------------------------------ //
  // Layer management                                                     //
  // ------------------------------------------------------------------ //
  function addLayer(url, label, initX, initY) {
    var canvas = _getCanvas();
    if (!canvas) return;

    var id = 'layer_' + (_nextLayerId++);
    var defaultW = Math.floor(canvas.width * 0.4);
    var maxZ = 0;
    canvasLayers.forEach(function (l) { if (l.zIndex > maxZ) maxZ = l.zIndex; });

    var hasCustomPos = (initX !== undefined && initY !== undefined);
    var layer = {
      id: id,
      img: null,
      x: hasCustomPos ? initX : Math.floor((canvas.width - defaultW) / 2),
      y: hasCustomPos ? initY : Math.floor((canvas.height - defaultW) / 2),
      w: defaultW,
      h: defaultW,
      zIndex: maxZ + 1,
      label: label || '',
      placeholderColor: _randomColor()
    };
    canvasLayers.push(layer);
    selectedLayerId = id;
    renderCanvas();
    renderSidebar();

    var imgEl = new Image();
    imgEl.onload = function () {
      var aspect = imgEl.naturalWidth / imgEl.naturalHeight;
      layer.w = defaultW;
      layer.h = Math.round(defaultW / aspect);
      if (!hasCustomPos) {
        layer.y = Math.floor((canvas.height - layer.h) / 2);
      }
      layer.img = imgEl;
      renderCanvas();
      renderSidebar();
    };
    imgEl.onerror = function () {
      // Proxy or network failure; placeholder rectangle persists
      renderCanvas();
      renderSidebar();
    };
    imgEl.src = url ? '/image-proxy?url=' + encodeURIComponent(url) : '';
  }

  function addOutfitLayers() {
    var canvas = _getCanvas();
    if (!_pendingOutfitItems || !canvas) return;
    var items = _pendingOutfitItems;
    _pendingOutfitItems = null;
    var offset = 0;
    items.forEach(function (item) {
      var x = Math.round(canvas.width * 0.25) + offset;
      var y = Math.round(canvas.height * 0.1) + offset;
      addLayer(item.image || '', item.name, x, y);
      offset += 30;
    });
  }

  function removeLayer(id) {
    canvasLayers = canvasLayers.filter(function (l) { return l.id !== id; });
    if (selectedLayerId === id) {
      selectedLayerId = canvasLayers.length
        ? canvasLayers[canvasLayers.length - 1].id
        : null;
    }
    renderCanvas();
    renderSidebar();
    _announce('Layer removed');
  }

  function moveLayerUp(id) {
    var layer = _layerById(id);
    if (!layer) return;
    var above = canvasLayers.filter(function (l) { return l.zIndex > layer.zIndex; });
    if (!above.length) return;
    above.sort(function (a, b) { return a.zIndex - b.zIndex; });
    var tmp = above[0].zIndex;
    above[0].zIndex = layer.zIndex;
    layer.zIndex = tmp;
    renderCanvas();
    renderSidebar();
  }

  function moveLayerDown(id) {
    var layer = _layerById(id);
    if (!layer) return;
    var below = canvasLayers.filter(function (l) { return l.zIndex < layer.zIndex; });
    if (!below.length) return;
    below.sort(function (a, b) { return b.zIndex - a.zIndex; });
    var tmp = below[0].zIndex;
    below[0].zIndex = layer.zIndex;
    layer.zIndex = tmp;
    renderCanvas();
    renderSidebar();
  }

  // ------------------------------------------------------------------ //
  // Sidebar (WN-113)                                                     //
  // ------------------------------------------------------------------ //
  function renderSidebar() {
    var sidebar = document.getElementById('style-canvas-sidebar');
    if (!sidebar) return;

    sidebar.innerHTML = '';

    // Saved items mini-grid
    var savedItems = [];
    try {
      savedItems = JSON.parse(localStorage.getItem('cloth_saved_items') || '[]');
    } catch (e) { /* localStorage unavailable */ }

    if (savedItems.length) {
      var savedHeading = document.createElement('h3');
      savedHeading.className = 'canvas-sidebar-heading';
      savedHeading.textContent = 'Saved items';
      sidebar.appendChild(savedHeading);

      var savedGrid = document.createElement('ul');
      savedGrid.className = 'canvas-saved-grid';

      savedItems.forEach(function (item) {
        var li = document.createElement('li');
        li.className = 'canvas-saved-card';

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'canvas-saved-card-btn';
        btn.setAttribute('aria-label', 'Add ' + item.name + ' as layer');

        if (item.image) {
          var img = document.createElement('img');
          img.src = item.image;
          img.alt = item.name;
          img.loading = 'lazy';
          img.className = 'canvas-saved-thumb';
          img.addEventListener('error', function () { img.style.display = 'none'; });
          btn.appendChild(img);
        }

        var nameEl = document.createElement('span');
        nameEl.className = 'canvas-saved-name';
        nameEl.textContent = item.name;
        btn.appendChild(nameEl);

        (function (capturedItem) {
          btn.addEventListener('click', function () {
            addLayer(capturedItem.image || '', capturedItem.name);
            _announce('Layer added');
          });
        }(item));

        li.appendChild(btn);
        savedGrid.appendChild(li);
      });

      sidebar.appendChild(savedGrid);
    }

    // Active layers list
    var layersHeading = document.createElement('h3');
    layersHeading.className = 'canvas-sidebar-heading';
    layersHeading.textContent = 'Layers';
    sidebar.appendChild(layersHeading);

    if (!canvasLayers.length) {
      var emptyMsg = document.createElement('p');
      emptyMsg.className = 'canvas-layers-empty';
      emptyMsg.textContent = 'No layers yet.';
      sidebar.appendChild(emptyMsg);
      return;
    }

    var layersList = document.createElement('ul');
    layersList.className = 'canvas-layers-list';

    // Show topmost layer first
    var sortedLayers = canvasLayers.slice().sort(function (a, b) { return b.zIndex - a.zIndex; });
    sortedLayers.forEach(function (layer) {
      var li = document.createElement('li');
      li.className = 'canvas-layer-item' + (layer.id === selectedLayerId ? ' is-selected' : '');

      var labelEl = document.createElement('span');
      labelEl.className = 'canvas-layer-label';
      labelEl.textContent = layer.label || 'Layer';

      var upBtn = document.createElement('button');
      upBtn.type = 'button';
      upBtn.className = 'canvas-layer-btn';
      upBtn.setAttribute('aria-label', 'Move ' + layer.label + ' up');
      upBtn.textContent = '↑';

      var downBtn = document.createElement('button');
      downBtn.type = 'button';
      downBtn.className = 'canvas-layer-btn';
      downBtn.setAttribute('aria-label', 'Move ' + layer.label + ' down');
      downBtn.textContent = '↓';

      var removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'canvas-layer-btn canvas-layer-remove';
      removeBtn.setAttribute('aria-label', 'Remove ' + layer.label);
      removeBtn.textContent = '×';

      (function (id) {
        li.addEventListener('click', function (e) {
          if (e.target.tagName === 'BUTTON') return;
          selectedLayerId = id;
          renderCanvas();
          renderSidebar();
        });
        upBtn.addEventListener('click', function () { moveLayerUp(id); });
        downBtn.addEventListener('click', function () { moveLayerDown(id); });
        removeBtn.addEventListener('click', function () { removeLayer(id); });
      }(layer.id));

      li.appendChild(labelEl);
      li.appendChild(upBtn);
      li.appendChild(downBtn);
      li.appendChild(removeBtn);
      layersList.appendChild(li);
    });

    sidebar.appendChild(layersList);
  }

  // ------------------------------------------------------------------ //
  // aria-live announcements (WN-115)                                    //
  // ------------------------------------------------------------------ //
  function _announce(msg) {
    var region = document.getElementById('style-canvas-live');
    if (!region) return;
    region.textContent = '';
    setTimeout(function () { region.textContent = msg; }, 50);
  }

  // ------------------------------------------------------------------ //
  // Pointer event handlers                                               //
  // ------------------------------------------------------------------ //
  function pointerDownHandler(e) {
    e.preventDefault();
    var canvas = _getCanvas();
    if (!canvas) return;

    // Track pointer for pinch detection (WN-115)
    _pinchPointers[e.pointerId] = { x: e.clientX, y: e.clientY };
    var pointerCount = Object.keys(_pinchPointers).length;

    if (pointerCount === 2 && selectedLayerId) {
      // Enter pinch-to-resize mode
      _pinchActive = true;
      _pinchLayerId = selectedLayerId;
      var pl = _layerById(selectedLayerId);
      if (pl) {
        _pinchOrigW = pl.w;
        _pinchOrigH = pl.h;
        _pinchStartDist = _pinchDist();
      }
      _dragging = false;
      _resizing = false;
      return;
    }

    var pos = _pointerPos(e);

    // Check resize handles on selected layer first
    if (selectedLayerId) {
      var sel = _layerById(selectedLayerId);
      if (sel) {
        var corner = _hitTestCorner(sel, pos.x, pos.y);
        if (corner) {
          _resizing = true;
          _resizeLayerId = selectedLayerId;
          _resizeCorner = corner;
          _resizeStartX = pos.x;
          _resizeStartY = pos.y;
          _resizeOrigLayer = { x: sel.x, y: sel.y, w: sel.w, h: sel.h };
          canvas.setPointerCapture(e.pointerId);
          return;
        }
      }
    }

    // Hit-test layers (topmost first)
    var hitId = _hitTestLayers(pos.x, pos.y);
    if (hitId) {
      selectedLayerId = hitId;
      var hitLayer = _layerById(hitId);
      _dragging = true;
      _dragLayerId = hitId;
      _dragOffsetX = pos.x - hitLayer.x;
      _dragOffsetY = pos.y - hitLayer.y;
      canvas.setPointerCapture(e.pointerId);
      renderCanvas();
      renderSidebar();
    } else {
      selectedLayerId = null;
      renderCanvas();
      renderSidebar();
    }
  }

  function pointerMoveHandler(e) {
    // Update tracked pointer position
    if (_pinchPointers[e.pointerId]) {
      _pinchPointers[e.pointerId] = { x: e.clientX, y: e.clientY };
    }

    // Pinch-to-resize (WN-115)
    if (_pinchActive && _pinchLayerId && _pinchStartDist > 0) {
      e.preventDefault();
      var newDist = _pinchDist();
      var scaleFactor = newDist / _pinchStartDist;
      var pl = _layerById(_pinchLayerId);
      if (pl) {
        pl.w = Math.max(20, Math.round(_pinchOrigW * scaleFactor));
        pl.h = Math.max(20, Math.round(_pinchOrigH * scaleFactor));
      }
      renderCanvas();
      return;
    }

    if (!_dragging && !_resizing) return;
    e.preventDefault();
    var pos = _pointerPos(e);

    if (_resizing) {
      var layer = _layerById(_resizeLayerId);
      if (!layer) return;
      var orig = _resizeOrigLayer;
      var dx = pos.x - _resizeStartX;
      var dy = pos.y - _resizeStartY;
      if (_resizeCorner === 'br') {
        layer.w = Math.max(20, orig.w + dx);
        layer.h = Math.max(20, orig.h + dy);
      } else if (_resizeCorner === 'bl') {
        layer.w = Math.max(20, orig.w - dx);
        layer.x = orig.x + orig.w - layer.w;
        layer.h = Math.max(20, orig.h + dy);
      } else if (_resizeCorner === 'tr') {
        layer.w = Math.max(20, orig.w + dx);
        layer.h = Math.max(20, orig.h - dy);
        layer.y = orig.y + orig.h - layer.h;
      } else if (_resizeCorner === 'tl') {
        layer.w = Math.max(20, orig.w - dx);
        layer.x = orig.x + orig.w - layer.w;
        layer.h = Math.max(20, orig.h - dy);
        layer.y = orig.y + orig.h - layer.h;
      }
      renderCanvas();
      return;
    }

    if (_dragging) {
      var dragLayer = _layerById(_dragLayerId);
      if (!dragLayer) return;
      dragLayer.x = pos.x - _dragOffsetX;
      dragLayer.y = pos.y - _dragOffsetY;
      renderCanvas();
    }
  }

  function pointerUpHandler(e) {
    if (e && e.pointerId !== undefined) {
      delete _pinchPointers[e.pointerId];
    }
    if (Object.keys(_pinchPointers).length < 2) {
      _pinchActive = false;
      _pinchLayerId = null;
    }
    _dragging = false;
    _resizing = false;
    _dragLayerId = null;
    _resizeLayerId = null;
    _resizeCorner = null;
    _resizeOrigLayer = null;
  }

  // ------------------------------------------------------------------ //
  // Focus trap (WN-115)                                                  //
  // ------------------------------------------------------------------ //
  function _trapFocus(e) {
    var modal = document.getElementById('style-canvas-modal');
    if (!modal || modal.style.display === 'none') return;

    var focusable = modal.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex="0"]'
    );
    var focusArr = Array.prototype.slice.call(focusable);
    if (!focusArr.length) return;

    var first = focusArr[0];
    var last = focusArr[focusArr.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  // ------------------------------------------------------------------ //
  // Modal open / close / base selection                                  //
  // ------------------------------------------------------------------ //
  function _openModal(garmentUrl, garmentName) {
    var modal = document.getElementById('style-canvas-modal');
    if (!modal) return;
    modal.style.display = '';
    modal._pendingUrl = garmentUrl;
    modal._pendingLabel = garmentName;

    // Reset state
    canvasLayers = [];
    selectedLayerId = null;
    baseImage = null;
    _dragging = false;
    _resizing = false;
    _pinchActive = false;
    _pinchPointers = {};
    _nextLayerId = 1;

    var baseSelector = document.getElementById('style-base-selector');
    var mainArea = document.getElementById('style-canvas-main');
    if (baseSelector) baseSelector.style.display = '';
    if (mainArea) mainArea.style.display = 'none';

    var ctx = _getCtx();
    var canvas = _getCanvas();
    if (ctx && canvas) ctx.clearRect(0, 0, canvas.width, canvas.height);

    var closeBtn = modal.querySelector('.style-canvas-close');
    if (closeBtn) closeBtn.focus();
  }

  function _closeModal() {
    var modal = document.getElementById('style-canvas-modal');
    if (!modal) return;
    modal.style.display = 'none';
    if (_triggerBtn && document.contains(_triggerBtn)) _triggerBtn.focus();
    _triggerBtn = null;
  }

  function _selectBase(imgSrc) {
    var modal = document.getElementById('style-canvas-modal');
    var baseSelector = document.getElementById('style-base-selector');
    var mainArea = document.getElementById('style-canvas-main');
    if (baseSelector) baseSelector.style.display = 'none';
    if (mainArea) mainArea.style.display = '';

    var pendingUrl = modal ? modal._pendingUrl : '';
    var pendingLabel = modal ? modal._pendingLabel : '';

    renderSidebar(); // populate sidebar while base loads

    var img = new Image();
    img.onload = function () {
      baseImage = img;
      renderCanvas();
      if (_pendingOutfitItems) {
        addOutfitLayers();
      } else if (pendingUrl) {
        addLayer(pendingUrl, pendingLabel);
      }
    };
    img.onerror = function () {
      // Base failed; proceed without it
      renderCanvas();
      if (_pendingOutfitItems) {
        addOutfitLayers();
      } else if (pendingUrl) {
        addLayer(pendingUrl, pendingLabel);
      }
    };
    img.src = imgSrc;
  }

  // ------------------------------------------------------------------ //
  // Wire modal events (called once on DOMContentLoaded)                  //
  // ------------------------------------------------------------------ //
  function _initModalEvents() {
    var modal = document.getElementById('style-canvas-modal');
    if (!modal) return;

    // Close button
    var closeBtn = modal.querySelector('.style-canvas-close');
    if (closeBtn) closeBtn.addEventListener('click', _closeModal);

    // Click on backdrop closes modal
    modal.addEventListener('click', function (e) {
      if (e.target === modal) _closeModal();
    });

    // Keyboard: Escape closes; Tab stays trapped; Ctrl+Z / Ctrl+Shift+Z undo (WN-161)
    document.addEventListener('keydown', function (e) {
      var m = document.getElementById('style-canvas-modal');
      if (!m || m.style.display === 'none') return;
      if (e.key === 'Escape') {
        _closeModal();
      } else if (e.key === 'Tab') {
        _trapFocus(e);
      } else if (e.key === 'z' && (e.ctrlKey || e.metaKey) && !e.shiftKey) {
        // Ctrl+Z / Cmd+Z — undo not yet available (WN-134 not done)
        // Guard: only intercept when focus is not in a text input outside canvas
        var active = document.activeElement;
        var isTextInput = active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA') && active.closest('#style-canvas-modal') === null;
        if (!isTextInput) {
          e.preventDefault();
          if (typeof window.showToast === 'function') window.showToast('Undo not yet available');
          _announce('Undo not yet available');
        }
      } else if (e.key === 'z' && (e.ctrlKey || e.metaKey) && e.shiftKey) {
        // Ctrl+Shift+Z / Cmd+Shift+Z — redo not yet available
        var active2 = document.activeElement;
        var isTextInput2 = active2 && (active2.tagName === 'INPUT' || active2.tagName === 'TEXTAREA') && active2.closest('#style-canvas-modal') === null;
        if (!isTextInput2) {
          e.preventDefault();
          if (typeof window.showToast === 'function') window.showToast('Redo not yet available');
          _announce('Redo not yet available');
        }
      }
    });

    // Silhouette picker buttons
    modal.querySelectorAll('.base-option[data-silhouette]').forEach(function (btn) {
      btn.addEventListener('click', function () { _selectBase(btn.dataset.silhouette); });
    });

    // Upload photo label
    var fileInput = document.getElementById('base-photo-upload');
    var uploadLabel = modal.querySelector('.base-option-upload');
    if (uploadLabel && fileInput) {
      uploadLabel.addEventListener('click', function (e) {
        e.preventDefault();
        fileInput.click();
      });
    }
    if (fileInput) {
      fileInput.addEventListener('change', function () {
        if (!fileInput.files || !fileInput.files[0]) return;
        var reader = new FileReader();
        reader.onload = function (ev) { _selectBase(ev.target.result); };
        reader.readAsDataURL(fileInput.files[0]);
      });
    }

    // Canvas pointer events
    var canvas = _getCanvas();
    if (canvas) {
      canvas.setAttribute('tabindex', '0');
      canvas.setAttribute('aria-label', 'Style canvas — use sidebar to add and arrange clothing layers');
      canvas.style.touchAction = 'none';
      canvas.addEventListener('pointerdown', pointerDownHandler);
      canvas.addEventListener('pointermove', pointerMoveHandler);
      canvas.addEventListener('pointerup', pointerUpHandler);
      canvas.addEventListener('pointerleave', pointerUpHandler);
      canvas.addEventListener('pointercancel', pointerUpHandler);
    }
  }

  // ------------------------------------------------------------------ //
  // Canvas save / load (WN-148)                                         //
  // ------------------------------------------------------------------ //
  var CANVAS_SAVES_KEY = 'cloth_canvas_saves';

  function _getCanvasSaves() {
    try { return JSON.parse(localStorage.getItem(CANVAS_SAVES_KEY) || '[]'); } catch (e) { return []; }
  }
  function _setCanvasSaves(saves) {
    try { localStorage.setItem(CANVAS_SAVES_KEY, JSON.stringify(saves)); } catch (e) { /* ignore */ }
  }

  function _saveCanvas() {
    var canvas = _getCanvas();
    if (!canvas) return;
    if (!canvasLayers.length && !baseImage) {
      _announce('Nothing to save — add a layer first');
      return;
    }
    var name = window.prompt('Name this canvas save:', 'My canvas');
    if (!name || !name.trim()) return;

    var serialisedLayers = canvasLayers.map(function (l) {
      return {id: l.id, src: l.img ? l.img.src : '', x: l.x, y: l.y, w: l.w, h: l.h, zIndex: l.zIndex, label: l.label, placeholderColor: l.placeholderColor};
    });
    var baseSrc = baseImage ? baseImage.src : null;
    var thumbnail = '';
    try { thumbnail = canvas.toDataURL('image/png'); } catch (e) { /* cross-origin */ }

    var save = {
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 5),
      name: name.trim(),
      savedAt: new Date().toISOString(),
      baseSrc: baseSrc,
      layers: serialisedLayers,
      thumbnail: thumbnail
    };
    var saves = _getCanvasSaves();
    saves.unshift(save);
    saves = saves.slice(0, 20); // keep last 20
    _setCanvasSaves(saves);
    _announce('Canvas saved');
    if (typeof window.renderCanvasSaves === 'function') window.renderCanvasSaves();
    if (typeof window.showToast === 'function') window.showToast('Canvas saved');
  }

  function _loadCanvasSave(save) {
    if (!save) return;
    _openModal('', '');

    // Restore base image then layers
    var doRestore = function () {
      save.layers.forEach(function (layerData) {
        var img = new Image();
        img.onload = function () {
          canvasLayers.push({
            id: _nextLayerId++,
            img: img,
            x: layerData.x, y: layerData.y,
            w: layerData.w, h: layerData.h,
            zIndex: layerData.zIndex,
            label: layerData.label || '',
            placeholderColor: layerData.placeholderColor || '#f0c0c0'
          });
          renderCanvas();
          renderSidebar();
        };
        img.onerror = function () {
          // Placeholder layer without image
          canvasLayers.push({
            id: _nextLayerId++,
            img: null,
            x: layerData.x, y: layerData.y,
            w: layerData.w, h: layerData.h,
            zIndex: layerData.zIndex,
            label: layerData.label || '',
            placeholderColor: layerData.placeholderColor || '#f0c0c0'
          });
          renderCanvas();
          renderSidebar();
        };
        if (layerData.src) { img.src = layerData.src; } else { img.dispatchEvent(new Event('error')); }
      });
    };

    var baseSelector = document.getElementById('style-base-selector');
    var mainArea = document.getElementById('style-canvas-main');

    if (save.baseSrc) {
      var baseImg = new Image();
      baseImg.onload = function () {
        baseImage = baseImg;
        if (baseSelector) baseSelector.style.display = 'none';
        if (mainArea) mainArea.style.display = '';
        renderSidebar();
        renderCanvas();
        doRestore();
      };
      baseImg.onerror = function () {
        if (baseSelector) baseSelector.style.display = 'none';
        if (mainArea) mainArea.style.display = '';
        renderSidebar();
        doRestore();
      };
      baseImg.src = save.baseSrc;
    } else {
      if (baseSelector) baseSelector.style.display = 'none';
      if (mainArea) mainArea.style.display = '';
      renderSidebar();
      doRestore();
    }
  }

  function _initSaveButton() {
    var actions = document.querySelector('.style-canvas-actions');
    if (!actions || actions._saveBtnBound) return;
    actions._saveBtnBound = true;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'style-canvas-save';
    btn.className = 'btn-secondary';
    btn.textContent = 'Save canvas';
    btn.addEventListener('click', _saveCanvas);
    // Insert after the download button
    var dlBtn = document.getElementById('style-canvas-download');
    if (dlBtn) dlBtn.insertAdjacentElement('afterend', btn);
    else actions.appendChild(btn);
  }

  // Expose load function for app.js to call
  window.loadCanvasSave = _loadCanvasSave;

  // ------------------------------------------------------------------ //
  // Download button (WN-114)                                             //
  // ------------------------------------------------------------------ //
  function _initDownloadButton() {
    var btn = document.getElementById('style-canvas-download');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var canvas = _getCanvas();
      if (!canvas) return;
      canvas.toBlob(function (blob) {
        if (!blob) return;
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'cloth-style-' + Date.now() + '.png';
        a.click();
        URL.revokeObjectURL(a.href);
        _announce('Image downloaded');
      }, 'image/png');
    });
  }

  // ------------------------------------------------------------------ //
  // "Style it" buttons (WN-114)                                          //
  // ------------------------------------------------------------------ //
  function initStyleItButtons() {
    document.querySelectorAll('.btn-style-it').forEach(function (btn) {
      if (btn.dataset.styleItBound) return;
      btn.dataset.styleItBound = '1';
      btn.addEventListener('click', function () {
        initStyleCanvas(btn.dataset.garmentUrl || '', btn.dataset.garmentName || '');
      });
    });

    document.querySelectorAll('.btn-open-canvas').forEach(function (btn) {
      if (btn.dataset.openCanvasBound) return;
      btn.dataset.openCanvasBound = '1';
      btn.addEventListener('click', function () {
        var outfitId = btn.getAttribute('data-outfit-id');
        var outfits = [];
        try {
          outfits = JSON.parse(localStorage.getItem('cloth_outfits') || '[]');
        } catch (e) { /* localStorage unavailable */ }
        var outfit = null;
        for (var i = 0; i < outfits.length; i++) {
          if (outfits[i].id === outfitId) { outfit = outfits[i]; break; }
        }
        if (!outfit || !outfit.items || !outfit.items.length) return;
        _pendingOutfitItems = outfit.items;
        _triggerBtn = btn;
        _openModal('', '');
      });
    });
  }

  // ------------------------------------------------------------------ //
  // Public: initStyleCanvas — called when "Style it" is clicked          //
  // ------------------------------------------------------------------ //
  function initStyleCanvas(garmentUrl, garmentName) {
    _triggerBtn = document.activeElement;
    _openModal(garmentUrl || '', garmentName || '');
  }

  // ------------------------------------------------------------------ //
  // DOMContentLoaded                                                      //
  // ------------------------------------------------------------------ //
  document.addEventListener('DOMContentLoaded', function () {
    _initModalEvents();
    _initDownloadButton();
    _initSaveButton();
    initStyleItButtons();
  });

  // Expose public API for cross-script access (app.js calls these after AJAX renders)
  window.initStyleCanvas = initStyleCanvas;
  window.initStyleItButtons = initStyleItButtons;

}());
