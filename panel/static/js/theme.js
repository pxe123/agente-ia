/**
 * ZapAction theme — Light / Dark (localStorage only, V1).
 */
(function (global) {
  "use strict";

  var STORAGE_KEY = "za-theme";
  var VALID = { light: true, dark: true };

  function getStored() {
    try {
      var t = localStorage.getItem(STORAGE_KEY);
      return VALID[t] ? t : "light";
    } catch (e) {
      return "light";
    }
  }

  function applyTheme(mode) {
    var m = VALID[mode] ? mode : "light";
    document.documentElement.setAttribute("data-theme", m);
    try {
      localStorage.setItem(STORAGE_KEY, m);
    } catch (e) {}
    syncToggleUI(m);
    try {
      global.dispatchEvent(new CustomEvent("zapaction-theme-change", { detail: { theme: m } }));
    } catch (e2) {}
    try {
      document.querySelectorAll("iframe").forEach(function (frame) {
        if (frame.contentWindow) {
          frame.contentWindow.postMessage({ type: "zapaction-theme", theme: m }, "*");
        }
      });
    } catch (e3) {}
    return m;
  }

  function getTheme() {
    var attr = document.documentElement.getAttribute("data-theme");
    if (VALID[attr]) return attr;
    return getStored();
  }

  function setTheme(mode) {
    return applyTheme(mode);
  }

  function toggleTheme() {
    return applyTheme(getTheme() === "dark" ? "light" : "dark");
  }

  function syncToggleUI(mode) {
    var m = mode || getTheme();
    var isDark = m === "dark";
    document.querySelectorAll("[data-za-theme-toggle]").forEach(function (btn) {
      var icon = btn.querySelector("[data-za-theme-icon]");
      if (icon) {
        icon.classList.remove("fa-sun", "fa-moon");
        icon.classList.add(isDark ? "fa-sun" : "fa-moon");
      }
      btn.setAttribute("aria-label", isDark ? "Alternar para modo claro" : "Alternar para modo escuro");
      btn.setAttribute("title", isDark ? "Modo claro" : "Modo escuro");
    });
    document.querySelectorAll('input[name="za_theme_mode"]').forEach(function (radio) {
      radio.checked = radio.value === m;
    });
  }

  function wireToggles() {
    document.querySelectorAll("[data-za-theme-toggle]").forEach(function (btn) {
      if (btn.__zaThemeWired) return;
      btn.__zaThemeWired = true;
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        toggleTheme();
      });
    });
    document.querySelectorAll('input[name="za_theme_mode"]').forEach(function (radio) {
      if (radio.__zaThemeWired) return;
      radio.__zaThemeWired = true;
      radio.addEventListener("change", function () {
        if (radio.checked) setTheme(radio.value);
      });
    });
    syncToggleUI();
  }

  function init() {
    applyTheme(getStored());
    wireToggles();
    global.addEventListener("storage", function (e) {
      if (e.key === STORAGE_KEY && VALID[e.newValue]) applyTheme(e.newValue);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  global.ZapActionTheme = {
    getTheme: getTheme,
    setTheme: setTheme,
    toggleTheme: toggleTheme,
    syncToggleUI: syncToggleUI,
  };
})(window);
