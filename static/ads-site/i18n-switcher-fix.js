/* Keep the /ads language switcher out of the content and make it touch-friendly. */
(() => {
  "use strict";

  const SWITCHER_ID = "pnl-language-switcher";
  const STYLE_ID = "pnl-language-switcher-mobile-fix";
  const labels = {
    ru: { flag: "🇷🇺", label: "Русский" },
    nl: { flag: "🇳🇱", label: "Nederlands" },
    en: { flag: "🇬🇧", label: "English" },
  };

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      #${SWITCHER_ID}.pnl-language-switcher {
        position: relative !important;
        inset: auto !important;
        top: auto !important;
        right: auto !important;
        bottom: auto !important;
        left: auto !important;
        z-index: 8 !important;
        display: flex !important;
        width: max-content !important;
        max-width: 100% !important;
        margin: 12px 0 2px auto !important;
        padding: 4px !important;
        gap: 3px !important;
        border: 1px solid rgba(24,24,24,.12) !important;
        border-radius: 999px !important;
        background: rgba(255,255,255,.94) !important;
        box-shadow: 0 6px 18px rgba(0,0,0,.08) !important;
        transform: none !important;
        pointer-events: auto !important;
      }
      #${SWITCHER_ID}.pnl-language-switcher button {
        display: grid !important;
        place-items: center !important;
        width: 46px !important;
        height: 46px !important;
        min-width: 46px !important;
        padding: 0 !important;
        border: 0 !important;
        border-radius: 999px !important;
        background: transparent !important;
        font: 400 25px/1 system-ui,-apple-system,"Segoe UI Emoji","Apple Color Emoji",sans-serif !important;
        letter-spacing: 0 !important;
        cursor: pointer !important;
        -webkit-tap-highlight-color: transparent;
        touch-action: manipulation;
      }
      #${SWITCHER_ID}.pnl-language-switcher button.active {
        background: #171717 !important;
        box-shadow: inset 0 0 0 1px rgba(255,255,255,.08) !important;
      }
      #${SWITCHER_ID}.pnl-language-switcher button:focus-visible {
        outline: 2px solid #c96b40 !important;
        outline-offset: 2px !important;
      }
      @media (max-width: 620px) {
        #${SWITCHER_ID}.pnl-language-switcher {
          margin-top: 10px !important;
          margin-bottom: 4px !important;
        }
        #${SWITCHER_ID}.pnl-language-switcher button {
          width: 44px !important;
          height: 44px !important;
          min-width: 44px !important;
          font-size: 24px !important;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function placeAndLabelSwitcher() {
    const switcher = document.getElementById(SWITCHER_ID);
    const header = document.querySelector("header.topbar");
    if (!switcher || !header) return false;

    ensureStyle();

    // Put the control in normal document flow: no overlap with header buttons or content.
    if (switcher.previousElementSibling !== header) {
      header.insertAdjacentElement("afterend", switcher);
    }

    switcher.querySelectorAll("button[data-lang]").forEach(button => {
      const item = labels[button.dataset.lang];
      if (!item) return;
      if (button.textContent !== item.flag) button.textContent = item.flag;
      button.setAttribute("aria-label", item.label);
      button.setAttribute("title", item.label);
    });
    return true;
  }

  function start() {
    placeAndLabelSwitcher();
    const observer = new MutationObserver(() => placeAndLabelSwitcher());
    observer.observe(document.documentElement, { childList: true, subtree: true });
    window.setInterval(placeAndLabelSwitcher, 800);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
