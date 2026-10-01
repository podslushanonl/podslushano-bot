(() => {
  'use strict';

  const nativeFetch = window.fetch.bind(window);
  const WELCOME_FLAG = 'pnlAdsWelcome2026';

  function setSignupMessage(sent) {
    const success = document.getElementById('giftSuccess');
    if (!success) return;
    success.textContent = sent
      ? '✓ Готово. Скидка активна — подтверждение отправили на e-mail.'
      : '✓ Готово. Скидка активна. Подписка сохранена — выберите подходящий формат.';
  }

  /* The existing signup handler already owns the form. We only observe its
     response so the UI can accurately say whether the welcome e-mail was sent. */
  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    const target = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
    if (target.includes('/ads-season/subscribe')) {
      response.clone().json().then((payload) => {
        if (!payload || !payload.ok) return;
        const sent = payload.email_sent !== false;
        setSignupMessage(sent);
        if (payload.email_sent) localStorage.setItem(WELCOME_FLAG, '1');
      }).catch(() => {});
    }
    return response;
  };

  function compactCopy() {
    const heroText = document.querySelector('.hero-copy > p');
    if (heroText) {
      heroText.textContent = 'Рекламные форматы для бизнеса, экспертов и проектов в Нидерландах. Выберите задачу — мы подготовим подачу и размещение.';
    }

    const howTitle = document.querySelector('#how .section-head h2');
    if (howTitle) howTitle.textContent = 'Как проходит размещение.';
    const howText = document.querySelector('#how .section-head > p');
    if (howText) howText.textContent = 'Вы выбираете формат и дату. Мы адаптируем материал под площадку и после оплаты фиксируем слот.';

    const formatsText = document.querySelector('#formats .section-head > p');
    if (formatsText) formatsText.textContent = 'Все цены уже включают 21% BTW.';

    const heroGift = document.querySelector('.hero-actions .gift-open');
    if (heroGift) heroGift.textContent = 'Забрать −26%';

    const giftTitle = document.getElementById('giftTitle');
    if (giftTitle) giftTitle.textContent = '−26% до конца года.';
    const giftText = document.querySelector('.gift-card > p');
    if (giftText) {
      giftText.textContent = 'Оставьте e-mail — активируем сезонную цену. Пишем редко: обычно одно письмо в начале месяца.';
    }
    const consent = document.querySelector('.consent span');
    if (consent) {
      consent.innerHTML = 'Я согласен(на) получать рекламные обновления Podslushano.nl. Отписаться можно в любой момент. <a href="/privacy?lang=ru" target="_blank" rel="noopener">Политика конфиденциальности</a>.';
    }
    const submit = document.getElementById('giftSubmit');
    if (submit) submit.textContent = 'Активировать −26%';
    setSignupMessage(false);

    const fab = document.getElementById('giftFab');
    if (fab && heroGift) {
      const syncHeroGift = () => {
        if (fab.classList.contains('unlocked')) heroGift.textContent = '−26% активна ✓';
      };
      syncHeroGift();
      new MutationObserver(syncHeroGift).observe(fab, {attributes: true, attributeFilter: ['class']});
    }
  }

  async function sendWelcomeForExistingSubscriber() {
    const token = localStorage.getItem('pnlAdsQ4Token') || '';
    if (!token || localStorage.getItem(WELCOME_FLAG) === '1') return;
    try {
      const response = await nativeFetch('/ads-season/welcome', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
        body: new URLSearchParams({token})
      });
      const payload = await response.json();
      if (response.ok && payload.ok && payload.email_sent) {
        localStorage.setItem(WELCOME_FLAG, '1');
      }
    } catch (_) {
      /* Welcome delivery must never block the page or the discount. */
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      compactCopy();
      window.setTimeout(sendWelcomeForExistingSubscriber, 350);
    });
  } else {
    compactCopy();
    window.setTimeout(sendWelcomeForExistingSubscriber, 350);
  }
})();
