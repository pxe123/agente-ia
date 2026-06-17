(function () {
  var root = document.getElementById('wh-routines-root');
  if (!root) return;

  var dayNames = [];
  try {
    dayNames = JSON.parse(root.getAttribute('data-day-names') || '[]');
  } catch (e) {
    dayNames = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
  }

  var state = { routines: [], day_overrides: {} };
  try {
    var initial = JSON.parse(root.getAttribute('data-initial-config') || '{}');
    if (initial && initial.routines) {
      state.routines = initial.routines;
      state.day_overrides = initial.day_overrides || {};
    }
  } catch (e2) { /* noop */ }

  if (!state.routines.length) {
    state.routines = [{
      id: uid(),
      name: 'Rotina principal',
      days: [0, 1, 2, 3, 4],
      open: '08:00',
      close: '18:00',
      lunch_enabled: true,
      lunch_start: '12:00',
      lunch_end: '13:00'
    }];
  }

  function uid() {
    return 'r-' + Math.random().toString(36).slice(2, 10);
  }

  function $(sel, ctx) {
    return (ctx || root).querySelector(sel);
  }

  function $all(sel, ctx) {
    return Array.prototype.slice.call((ctx || root).querySelectorAll(sel));
  }

  function daysTaken(excludeRoutineId) {
    var taken = {};
    state.routines.forEach(function (r) {
      if (r.id === excludeRoutineId) return;
      (r.days || []).forEach(function (d) { taken[d] = true; });
    });
    Object.keys(state.day_overrides || {}).forEach(function (k) {
      var ov = state.day_overrides[k];
      if (ov && ov.custom) taken[parseInt(k, 10)] = true;
    });
    return taken;
  }

  function routineSummary(r) {
    var labels = (r.days || []).map(function (d) {
      return dayNames[d] ? dayNames[d].slice(0, 3) : String(d);
    }).join(', ');
    if (!labels) return r.name + ': sem dias';
    if (r.lunch_enabled) {
      return labels + ' ' + r.open + '–' + r.lunch_start + ' e ' + r.lunch_end + '–' + r.close;
    }
    return labels + ' ' + r.open + '–' + r.close;
  }

  function syncSummary() {
    var el = document.getElementById('wh-routines-summary');
    if (!el) return;
    var parts = state.routines.map(routineSummary);
    var customDays = Object.keys(state.day_overrides || {}).filter(function (k) {
      return state.day_overrides[k] && state.day_overrides[k].custom;
    });
    if (customDays.length) {
      parts.push(customDays.length + ' dia(s) personalizado(s)');
    }
    el.textContent = 'Resumo: ' + (parts.join(' · ') || '—');
  }

  function renderRoutineCard(routine) {
    var taken = daysTaken(routine.id);
    var card = document.createElement('div');
    card.className = 'rounded-xl border border-slate-200 bg-slate-50/60 p-4 space-y-3';
    card.dataset.routineId = routine.id;

    var head = document.createElement('div');
    head.className = 'flex flex-wrap items-center justify-between gap-2';
    head.innerHTML =
      '<input type="text" class="wh-routine-name flex-1 min-w-[140px] border border-slate-200 rounded-lg px-3 py-1.5 text-sm font-semibold" value="' + esc(routine.name) + '">' +
      '<button type="button" class="wh-remove-routine text-xs text-red-700 font-semibold hover:underline"' +
      (state.routines.length <= 1 ? ' disabled style="opacity:0.4"' : '') + '>Remover</button>';
    card.appendChild(head);

    var daysWrap = document.createElement('div');
    daysWrap.className = 'flex flex-wrap gap-2';
    for (var d = 0; d < 7; d++) {
      var label = document.createElement('label');
      label.className = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-sm cursor-pointer hover:bg-white';
      var checked = (routine.days || []).indexOf(d) >= 0;
      var disabled = taken[d] && !checked;
      label.innerHTML =
        '<input type="checkbox" class="wh-routine-day rounded border-slate-300" value="' + d + '"' +
        (checked ? ' checked' : '') + (disabled ? ' disabled' : '') + '>' +
        '<span>' + esc(dayNames[d] ? dayNames[d].slice(0, 3) : d) + '</span>';
      daysWrap.appendChild(label);
    }
    card.appendChild(daysWrap);

    var times = document.createElement('div');
    times.className = 'flex flex-wrap gap-4 items-end';
    times.innerHTML =
      '<div><label class="text-xs font-medium text-slate-500">Abre às</label>' +
      '<input type="time" class="wh-routine-open block border border-slate-200 rounded-xl px-3 py-2 text-sm mt-1" value="' + esc(routine.open) + '"></div>' +
      '<div><label class="text-xs font-medium text-slate-500">Fecha às</label>' +
      '<input type="time" class="wh-routine-close block border border-slate-200 rounded-xl px-3 py-2 text-sm mt-1" value="' + esc(routine.close) + '"></div>';
    card.appendChild(times);

    var lunch = document.createElement('div');
    lunch.className = 'space-y-2';
    lunch.innerHTML =
      '<label class="inline-flex items-center gap-2 text-sm">' +
      '<input type="checkbox" class="wh-routine-lunch rounded border-slate-300"' + (routine.lunch_enabled ? ' checked' : '') + '> Pausa para almoço</label>' +
      '<div class="wh-lunch-fields flex flex-wrap gap-4 items-end' + (routine.lunch_enabled ? '' : ' hidden') + '">' +
      '<div><label class="text-xs font-medium text-slate-500">Das</label>' +
      '<input type="time" class="wh-routine-lunch-start block border border-slate-200 rounded-xl px-3 py-2 text-sm mt-1" value="' + esc(routine.lunch_start) + '"></div>' +
      '<div><label class="text-xs font-medium text-slate-500">às</label>' +
      '<input type="time" class="wh-routine-lunch-end block border border-slate-200 rounded-xl px-3 py-2 text-sm mt-1" value="' + esc(routine.lunch_end) + '"></div></div>';
    card.appendChild(lunch);

    card.querySelector('.wh-routine-lunch').addEventListener('change', function (e) {
      card.querySelector('.wh-lunch-fields').classList.toggle('hidden', !e.target.checked);
      readFromDom();
      syncSummary();
    });
    card.querySelector('.wh-remove-routine').addEventListener('click', function () {
      if (state.routines.length <= 1) return;
      state.routines = state.routines.filter(function (r) { return r.id !== routine.id; });
      renderAll();
    });

    $all('input', card).forEach(function (inp) {
      inp.addEventListener('change', function () {
        readFromDom();
        renderRoutines();
        syncSummary();
      });
    });

    return card;
  }

  function renderDayOverrides() {
    var wrap = document.getElementById('wh-day-overrides');
    if (!wrap) return;
    wrap.innerHTML = '';
    for (var d = 0; d < 7; d++) {
      var key = String(d);
      var ov = state.day_overrides[key] || { custom: false, intervals: [{ start: '09:00', end: '18:00' }] };
      if (!ov.intervals || !ov.intervals.length) {
        ov.intervals = [{ start: '09:00', end: '18:00' }];
      }
      var block = document.createElement('div');
      block.className = 'rounded-lg border border-slate-200 p-3 bg-slate-50/40';
      block.dataset.day = key;

      var head = document.createElement('label');
      head.className = 'inline-flex items-center gap-2 text-sm font-medium text-slate-800';
      head.innerHTML =
        '<input type="checkbox" class="wh-day-custom rounded border-slate-300"' + (ov.custom ? ' checked' : '') + '>' +
        '<span>' + esc(dayNames[d] || ('Dia ' + d)) + '</span>';
      block.appendChild(head);

      var body = document.createElement('div');
      body.className = 'wh-day-custom-body mt-3 space-y-2' + (ov.custom ? '' : ' hidden');
      ov.intervals.forEach(function (iv, idx) {
        body.appendChild(intervalRow(key, iv, idx));
      });
      var addBtn = document.createElement('button');
      addBtn.type = 'button';
      addBtn.className = 'wh-add-interval text-xs text-teal-700 font-semibold hover:underline';
      addBtn.textContent = '+ Intervalo';
      body.appendChild(addBtn);
      block.appendChild(body);

      head.querySelector('.wh-day-custom').addEventListener('change', function (e) {
        body.classList.toggle('hidden', !e.target.checked);
        readFromDom();
        renderRoutines();
        syncSummary();
      });
      addBtn.addEventListener('click', function () {
        if (!state.day_overrides[key]) {
          state.day_overrides[key] = { custom: true, intervals: [] };
        }
        state.day_overrides[key].custom = true;
        state.day_overrides[key].intervals.push({ start: '09:00', end: '18:00' });
        renderDayOverrides();
        readFromDom();
        renderRoutines();
        syncSummary();
      });

      wrap.appendChild(block);
    }
    bindIntervalEvents();
  }

  function intervalRow(dayKey, iv, idx) {
    var row = document.createElement('div');
    row.className = 'flex flex-wrap items-end gap-2';
    row.innerHTML =
      '<div><label class="text-xs text-slate-500">Início</label>' +
      '<input type="time" class="wh-iv-start border border-slate-200 rounded-lg px-2 py-1.5 text-sm" value="' + esc(iv.start || '09:00') + '"></div>' +
      '<div><label class="text-xs text-slate-500">Fim</label>' +
      '<input type="time" class="wh-iv-end border border-slate-200 rounded-lg px-2 py-1.5 text-sm" value="' + esc(iv.end || '18:00') + '"></div>' +
      '<button type="button" class="wh-remove-interval text-xs text-red-600 font-semibold mb-1">Remover</button>';
    row.dataset.day = dayKey;
    row.dataset.idx = String(idx);
    return row;
  }

  function bindIntervalEvents() {
    $all('.wh-remove-interval').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var row = btn.closest('[data-day]');
        if (!row) return;
        var dayKey = row.dataset.day;
        var idx = parseInt(row.dataset.idx, 10);
        var ov = state.day_overrides[dayKey];
        if (!ov || !ov.intervals) return;
        ov.intervals.splice(idx, 1);
        if (!ov.intervals.length) ov.intervals.push({ start: '09:00', end: '18:00' });
        renderDayOverrides();
        readFromDom();
        syncSummary();
      });
    });
    $all('.wh-iv-start, .wh-iv-end').forEach(function (inp) {
      inp.addEventListener('change', function () {
        readFromDom();
        syncSummary();
      });
    });
  }

  function readFromDom() {
    var list = document.getElementById('wh-routines-list');
    if (!list) return;
    $all('[data-routine-id]', list).forEach(function (card) {
      var id = card.dataset.routineId;
      var routine = state.routines.find(function (r) { return r.id === id; });
      if (!routine) return;
      routine.name = (card.querySelector('.wh-routine-name') || {}).value || 'Rotina';
      routine.days = [];
      $all('.wh-routine-day:checked', card).forEach(function (cb) {
        routine.days.push(parseInt(cb.value, 10));
      });
      routine.days.sort();
      routine.open = (card.querySelector('.wh-routine-open') || {}).value || '08:00';
      routine.close = (card.querySelector('.wh-routine-close') || {}).value || '18:00';
      var lunchCb = card.querySelector('.wh-routine-lunch');
      routine.lunch_enabled = lunchCb ? lunchCb.checked : false;
      routine.lunch_start = (card.querySelector('.wh-routine-lunch-start') || {}).value || '12:00';
      routine.lunch_end = (card.querySelector('.wh-routine-lunch-end') || {}).value || '13:00';
    });

    var overrides = {};
    $all('#wh-day-overrides > [data-day]').forEach(function (block) {
      var dayKey = block.dataset.day;
      var customCb = block.querySelector('.wh-day-custom');
      if (!customCb || !customCb.checked) return;
      var intervals = [];
      $all('.wh-iv-start', block).forEach(function (startInp, i) {
        var endInp = $all('.wh-iv-end', block)[i];
        if (startInp && endInp) {
          intervals.push({ start: startInp.value, end: endInp.value });
        }
      });
      if (intervals.length) {
        overrides[dayKey] = { custom: true, intervals: intervals };
      }
    });
    state.day_overrides = overrides;
  }

  function renderRoutines() {
    readFromDom();
    var list = document.getElementById('wh-routines-list');
    if (!list) return;
    list.innerHTML = '';
    state.routines.forEach(function (r) {
      list.appendChild(renderRoutineCard(r));
    });
  }

  function renderAll() {
    renderRoutines();
    renderDayOverrides();
    syncSummary();
  }

  function esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  document.getElementById('wh-add-routine').addEventListener('click', function () {
    state.routines.push({
      id: uid(),
      name: 'Rotina ' + (state.routines.length + 1),
      days: [],
      open: '09:00',
      close: '13:00',
      lunch_enabled: false,
      lunch_start: '12:00',
      lunch_end: '13:00'
    });
    renderAll();
  });

  var form = document.getElementById('wh-save-form');
  if (form) {
    form.addEventListener('submit', function (e) {
      readFromDom();
      var hasDays = state.routines.some(function (r) { return (r.days || []).length > 0; });
      var hasOverrides = Object.keys(state.day_overrides || {}).length > 0;
      if (!hasDays && !hasOverrides) {
        e.preventDefault();
        alert('Selecione pelo menos um dia numa rotina ou personalize um dia.');
        return;
      }
      var hidden = document.getElementById('wh-routines-json');
      if (hidden) {
        hidden.value = JSON.stringify({
          routines: state.routines,
          day_overrides: state.day_overrides
        });
      }
    });
  }

  renderAll();
})();
