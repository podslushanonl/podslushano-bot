(() => {
  'use strict';

  const nativeFetch = window.fetch.bind(window);
  const WELCOME_FLAG = 'pnlAdsWelcome2026';
  const SEASON_TOKEN = 'pnlAdsQ4Token';

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
      giftText.textContent = 'Оставьте e-mail — активируем −26% на все рекламные форматы, включая Contact Guide.';
    }
    const consent = document.querySelector('.consent span');
    if (consent) {
      consent.innerHTML = 'Я согласен(на) получать рекламные обновления Podslushano.nl. Обычно 1 письмо в месяц, максимум 2 при отдельном важном поводе. Отписаться можно в любой момент. <a href="/privacy?lang=ru" target="_blank" rel="noopener">Политика конфиденциальности</a>.';
    }
    const submit = document.getElementById('giftSubmit');
    if (submit) submit.textContent = 'Активировать −26%';
    setSignupMessage(false);

    const fab = document.getElementById('giftFab');
    if (fab && heroGift) {
      const syncHeroGift = () => {
        const active = fab.classList.contains('unlocked');
        heroGift.textContent = active ? '−26% активна ✓' : 'Забрать −26%';
        fab.setAttribute('aria-label', active ? 'Скидка 26 процентов активна' : 'Получить скидку 26 процентов');
      };
      syncHeroGift();
      new MutationObserver(syncHeroGift).observe(fab, {attributes: true, attributeFilter: ['class']});
    }
  }

  function removeGiftIntro() {
    const intro = document.getElementById('giftIntro');
    if (!intro) return;
    intro.classList.add('is-hiding');
    window.setTimeout(() => intro.remove(), 220);
  }

  function showGiftIntro() {
    if (document.getElementById('giftIntro')) return;
    const fab = document.getElementById('giftFab');
    if (fab && fab.classList.contains('unlocked')) return;

    const intro = document.createElement('div');
    intro.className = 'gift-intro';
    intro.id = 'giftIntro';
    intro.innerHTML = `
      <div class="gift-intro-card" role="button" tabindex="0" aria-label="Открыть подарок и получить скидку 26 процентов">
        <button type="button" class="gift-intro-close" aria-label="Закрыть">×</button>
        <div class="gift-intro-icon">🎁</div>
        <strong>У вас подарок</strong>
        <span>Нажмите, чтобы открыть</span>
      </div>`;
    document.body.appendChild(intro);

    const open = () => {
      removeGiftIntro();
      const trigger = document.querySelector('.hero-actions .gift-open');
      if (trigger) window.setTimeout(() => trigger.click(), 90);
    };
    const card = intro.querySelector('.gift-intro-card');
    card.addEventListener('click', (event) => {
      if (event.target.closest('.gift-intro-close')) return;
      open();
    });
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        open();
      }
    });
    intro.querySelector('.gift-intro-close').addEventListener('click', (event) => {
      event.stopPropagation();
      removeGiftIntro();
    });
    intro.addEventListener('click', (event) => {
      if (event.target === intro) removeGiftIntro();
    });
  }

  function initGiftExperience() {
    const fab = document.getElementById('giftFab');
    if (fab) {
      const sync = () => {
        if (fab.classList.contains('unlocked')) removeGiftIntro();
      };
      new MutationObserver(sync).observe(fab, {attributes: true, attributeFilter: ['class']});
    }

    if (!localStorage.getItem(SEASON_TOKEN)) {
      window.setTimeout(showGiftIntro, 220);
    } else {
      /* restoreSeason() runs in the base page. If that token is stale it removes
         it; in that case bring the gift back instead of silently losing the offer. */
      window.setTimeout(() => {
        if (!localStorage.getItem(SEASON_TOKEN) && !(fab && fab.classList.contains('unlocked'))) {
          showGiftIntro();
        }
      }, 1100);
    }
  }

  async function sendWelcomeForExistingSubscriber() {
    const token = localStorage.getItem(SEASON_TOKEN) || '';
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

  function loadLanguageSwitcherFix() {
    if (document.querySelector('script[data-pnl-language-switcher-fix]')) return;
    const script = document.createElement('script');
    script.src = '/ads-static/i18n-switcher-fix.js';
    script.dataset.pnlLanguageSwitcherFix = '1';
    script.async = false;
    document.head.appendChild(script);
  }

  function boot() {
    loadLanguageSwitcherFix();
    compactCopy();
    initGiftExperience();
    window.setTimeout(sendWelcomeForExistingSubscriber, 350);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();