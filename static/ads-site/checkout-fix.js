/* Preserve the redesigned Q4 booking flow on backend validation/payment errors. */
(() => {
  'use strict';
  const form = document.getElementById('bookingForm');
  if (!form) return;

  // The Q4 campaign Guide step and the backend must agree on what qualifies
  // as a public contact. Normalise common "Instagram: username" entries.
  function normalisePublicContact() {
    const field = document.getElementById('guideContact');
    if (!field) return '';
    const value = field.value.trim();
    const instagram = value.match(/^(?:instagram|insta|ig)\s*[:\-–]\s*@?([A-Za-z0-9._]{1,30})\s*$/i);
    const telegram = value.match(/^(?:telegram|tg)\s*[:\-–]\s*@?([A-Za-z0-9_]{5,32})\s*$/i);
    if (instagram) field.value = 'https://instagram.com/' + instagram[1];
    if (telegram) field.value = 'https://t.me/' + telegram[1];
    return field.value.trim();
  }

  function validPublicContact(value) {
    if (value.length < 5 || value.length > 300) return false;
    return (value.match(/\d/g) || []).length >= 7
      || /(^|[^\w])@[A-Za-z0-9_]{5,32}\b/.test(value)
      || /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/.test(value)
      || /(?:https?:\/\/|www\.)\S+|\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b/i.test(value);
  }

  const originalValidateGuide = window.validateGuide;
  if (typeof originalValidateGuide === 'function') {
    window.validateGuide = function () {
      if (productId === 'ad_campaign') {
        const value = normalisePublicContact();
        if (!validPublicContact(value)) {
          showErr('guideError', 'Укажите ссылку на Instagram или Telegram, @ник, e-mail или телефон. Например: https://instagram.com/yourname');
          return false;
        }
      }
      return originalValidateGuide();
    };
  }

  function showCheckoutError(message) {
    const text = message || 'Не удалось создать оплату. Попробуйте ещё раз.';
    let step = 'review';
    let id = 'reviewError';
    if (productId === 'ad_campaign' && /контакт|карточк|contact guide|фото|логотип|описани|категори|город|специалист/i.test(text)) {
      step = 'guide';
      id = 'guideError';
    } else if (/дат|занят|слот|месяц|ближайших/i.test(text)) {
      step = 'date';
      id = 'dateError';
      if (typeof loadTaken === 'function') loadTaken();
    } else if (/фактур|счёт|адрес|плательщик|компани|почтовый|индекс|e-mail/i.test(text)) {
      step = 'invoice';
      id = 'invoiceError';
    }
    if (typeof go === 'function') go(step);
    if (typeof showErr === 'function') showErr(id, text);
  }

  // Defer installation until all inline and campaign-guide-photo.js validators
  // have attached. A previously prevented submit must never create a payment.
  window.addEventListener('load', () => {
    let pending = false;
    let checkoutCreated = false;
    const button = form.querySelector('button[type="submit"]');
    form.addEventListener('submit', async (event) => {
      if (event.defaultPrevented) return;
      event.preventDefault();
      // Do not create a second pending order if Mollie navigation was blocked.
      if (pending || checkoutCreated) return;
      pending = true;
      const oldLabel = button ? button.textContent : '';
      if (button) {
        button.disabled = true;
        button.textContent = 'Создаём оплату…';
      }
      try {
        // Native form validators have already prepared hidden fmt, opt, dates
        // and phonePayload (signed Q4 entitlement + optional Guide photo).
        const response = await fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          headers: { 'Accept': 'application/json' },
          credentials: 'same-origin',
          cache: 'no-store'
        });
        if (!(response.headers.get('content-type') || '').includes('application/json')) {
          throw new Error('Сервер не вернул ответ об оплате. Повторите попытку.');
        }
        const payload = await response.json();
        if (!response.ok || !payload.ok || !payload.checkout_url) {
          showCheckoutError(payload.error || 'Не удалось создать оплату.');
          return;
        }

        checkoutCreated = true;
        // Keep a manual link as a fallback for in-app browsers that prevent
        // top-frame navigation after an asynchronous request.
        const errorBox = document.getElementById('reviewError');
        if (errorBox) {
          errorBox.textContent = 'Оплата готова. Если Mollie не открылся, нажмите: ';
          const link = document.createElement('a');
          link.href = payload.checkout_url;
          link.target = '_blank';
          link.rel = 'noopener';
          link.textContent = 'Открыть Mollie';
          errorBox.appendChild(link);
          errorBox.classList.add('show');
        }
        try {
          if (window.top && window.top !== window.self) window.top.location.href = payload.checkout_url;
          else window.location.assign(payload.checkout_url);
        } catch (_) {
          window.location.assign(payload.checkout_url);
        }
      } catch (err) {
        showCheckoutError(err && err.message ? err.message : 'Ошибка связи с сервером. Попробуйте ещё раз.');
      } finally {
        pending = false;
        if (button) {
          button.disabled = checkoutCreated;
          button.textContent = checkoutCreated ? 'Оплата создана — откройте Mollie' : oldLabel;
        }
      }
    });
  }, { once: true });
})();
