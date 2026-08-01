(() => {
  "use strict";

  const preferenceKey = "somnisignal-theme";
  const media = window.matchMedia("(prefers-color-scheme: light)");

  function storedTheme() {
    try {
      const value = window.localStorage.getItem(preferenceKey);
      return value === "light" || value === "dark" ? value : null;
    } catch {
      return null;
    }
  }

  function preferredTheme() {
    return storedTheme() || (media.matches ? "light" : "dark");
  }

  function updateControls(theme) {
    document.querySelectorAll(".theme-toggle").forEach((control) => {
      const nextTheme = theme === "dark" ? "light" : "dark";
      const icon = control.querySelector("span");
      const label = control.querySelector("b");
      if (icon) icon.textContent = nextTheme === "light" ? "☀" : "◐";
      if (label) label.textContent = nextTheme;
      control.setAttribute("aria-label", `Switch to ${nextTheme} mode`);
      control.setAttribute("title", `Switch to ${nextTheme} mode`);
    });
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    if (document.readyState !== "loading") updateControls(theme);
  }

  applyTheme(preferredTheme());

  document.addEventListener("DOMContentLoaded", () => {
    updateControls(document.documentElement.dataset.theme || preferredTheme());
    document.querySelectorAll(".theme-toggle").forEach((control) => {
      control.addEventListener("click", () => {
        const current = document.documentElement.dataset.theme || preferredTheme();
        const next = current === "dark" ? "light" : "dark";
        try { window.localStorage.setItem(preferenceKey, next); } catch { /* preference remains session-only */ }
        applyTheme(next);
      });
    });
  });

  media.addEventListener("change", () => {
    if (!storedTheme()) applyTheme(preferredTheme());
  });
})();
