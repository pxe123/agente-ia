/**
 * Máscara fixa de telefone BR no painel de agenda: (11) 99999-9999
 * Aceita no máximo 11 dígitos (DDD + celular). O DDI 55 é aplicado no servidor.
 */
(function () {
  function digitsOnly(v) {
    return (v || "").replace(/\D/g, "");
  }

  function localDigits(raw) {
    var d = digitsOnly(raw);
    if (d.indexOf("55") === 0 && d.length > 11) d = d.slice(2);
    return d.slice(0, 11);
  }

  function formatLocal(d) {
    if (!d) return "";
    if (d.length <= 2) return "(" + d;
    if (d.length <= 6) return "(" + d.slice(0, 2) + ") " + d.slice(2);
    if (d.length <= 10) return "(" + d.slice(0, 2) + ") " + d.slice(2, 6) + "-" + d.slice(6);
    return "(" + d.slice(0, 2) + ") " + d.slice(2, 7) + "-" + d.slice(7, 11);
  }

  function applyMask(el) {
    el.value = formatLocal(localDigits(el.value));
  }

  function isCompletePhone(el) {
    var n = localDigits(el.value).length;
    return n === 10 || n === 11;
  }

  function bindPanelContactPhone(el) {
    if (!el || el.getAttribute("data-phone-mask") === "1") return;
    el.setAttribute("data-phone-mask", "1");
    el.setAttribute("maxlength", "15");
    el.setAttribute("placeholder", "(11) 99999-9999");

    el.addEventListener("keydown", function (e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      var allowed = ["Backspace", "Delete", "Tab", "ArrowLeft", "ArrowRight", "Home", "End", "Enter"];
      if (allowed.indexOf(e.key) >= 0) return;
      if (localDigits(el.value).length >= 11 && /^\d$/.test(e.key)) {
        e.preventDefault();
      }
    });

    el.addEventListener("input", function () {
      applyMask(el);
      if (!el.value) el.setCustomValidity("");
      else if (isCompletePhone(el)) el.setCustomValidity("");
    });

    el.addEventListener("blur", function () {
      applyMask(el);
      var n = localDigits(el.value).length;
      if (n > 0 && n < 10) {
        el.setCustomValidity("Informe o DDD e o número completo, ex.: (11) 99999-9999");
      } else {
        el.setCustomValidity("");
      }
    });

    el.addEventListener("paste", function (e) {
      e.preventDefault();
      var text = (e.clipboardData || window.clipboardData).getData("text") || "";
      el.value = formatLocal(localDigits(text));
    });

    var form = el.closest("form");
    if (form && form.getAttribute("data-phone-validate") !== "1") {
      form.setAttribute("data-phone-validate", "1");
      form.addEventListener("submit", function (ev) {
        var invalid = null;
        form.querySelectorAll(".js-panel-contact-phone").forEach(function (input) {
          var n = localDigits(input.value).length;
          if (n === 0) {
            input.setCustomValidity("");
            return;
          }
          if (n < 10 || n > 11) {
            input.setCustomValidity("Telefone incompleto. Use (11) 99999-9999 ou (11) 9999-9999.");
            if (!invalid) invalid = input;
          } else {
            input.setCustomValidity("");
          }
        });
        if (invalid) {
          ev.preventDefault();
          invalid.reportValidity();
        }
      });
    }

    applyMask(el);
  }

  function initAll(root) {
    (root || document).querySelectorAll(".js-panel-contact-phone").forEach(bindPanelContactPhone);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { initAll(); });
  } else {
    initAll();
  }

  window.initPanelContactPhoneInputs = initAll;
})();
