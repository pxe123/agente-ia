(function () {
  var form = document.getElementById('wh-clinic-advanced-form');
  var applyBtn = document.getElementById('wh-simple-apply');
  if (!form || !applyBtn) return;

  var dayNames = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];

  function summaryText() {
    var checked = [];
    document.querySelectorAll('.wh-day-cb:checked').forEach(function (cb) {
      checked.push(parseInt(cb.value, 10));
    });
    if (!checked.length) return 'Selecione pelo menos um dia.';
    var open = document.getElementById('wh-open').value || '08:00';
    var close = document.getElementById('wh-close').value || '18:00';
    var lunch = document.getElementById('wh-lunch').checked;
    var lunchStart = document.getElementById('wh-lunch-start').value || '12:00';
    var lunchEnd = document.getElementById('wh-lunch-end').value || '13:00';
    var labels = checked.map(function (d) { return dayNames[d] ? dayNames[d].slice(0, 3) : d; }).join(', ');
    if (lunch) {
      return labels + ' ' + open + '–' + lunchStart + ' e ' + lunchEnd + '–' + close;
    }
    return labels + ' ' + open + '–' + close;
  }

  function syncSummary() {
    var el = document.getElementById('wh-simple-summary');
    if (el) el.textContent = 'Resumo: ' + summaryText();
  }

  document.querySelectorAll('.wh-day-cb, #wh-open, #wh-close, #wh-lunch, #wh-lunch-start, #wh-lunch-end').forEach(function (el) {
    el.addEventListener('change', syncSummary);
  });
  syncSummary();

  applyBtn.addEventListener('click', function () {
    var open = document.getElementById('wh-open').value || '08:00';
    var close = document.getElementById('wh-close').value || '18:00';
    var lunch = document.getElementById('wh-lunch').checked;
    var lunchStart = document.getElementById('wh-lunch-start').value || '12:00';
    var lunchEnd = document.getElementById('wh-lunch-end').value || '13:00';
    var days = [];
    document.querySelectorAll('.wh-day-cb:checked').forEach(function (cb) {
      days.push(parseInt(cb.value, 10));
    });
    if (!days.length) {
      alert('Selecione pelo menos um dia da semana.');
      return;
    }
    var dowSelect = form.querySelector('[name="day_of_week"]');
    var startInput = form.querySelector('[name="start_time"]');
    var endInput = form.querySelector('[name="end_time"]');
    if (!dowSelect || !startInput || !endInput) return;

    var first = days[0];
    dowSelect.value = String(first);
    if (lunch) {
      startInput.value = open;
      endInput.value = lunchStart;
    } else {
      startInput.value = open;
      endInput.value = close;
    }
    form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    var adv = document.getElementById('wh-advanced-details');
    if (adv && !adv.open) adv.open = true;
    var hint = document.getElementById('wh-prefill-hint');
    if (hint) {
      var extra = lunch ? ' Depois adicione o intervalo da tarde (' + lunchEnd + '–' + close + ').' : '';
      hint.textContent = 'Formulário pré-preenchido para ' + dayNames[first] + extra + ' Clique «Adicionar intervalo» e repita para os outros dias se necessário.';
      hint.classList.remove('hidden');
    }
  });
})();
