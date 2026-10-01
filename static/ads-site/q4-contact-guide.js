(() => {
  'use strict';

  const PLAN_PRICES = {
    month: {label: 'Standard · 1 месяц', base: 9.99, sale: 7.39},
    year: {label: 'Standard · 12 месяцев', base: 99, sale: 73.26},
    month_premium: {label: 'Premium · 1 месяц', base: 19.99, sale: 14.79},
    '6m_premium': {label: 'Premium · 6 месяцев', base: 109, sale: 80.66},
    year_premium: {label: 'Premium · 12 месяцев', base: 199, sale: 147.26}
  };

  function euro(value) {
    return '€' + Number(value).toLocaleString('ru-RU', {
      minimumFractionDigits: Number(value) % 1 ? 2 : 0,
      maximumFractionDigits: 2
    });
  }

  function seasonToken() {
    return localStorage.getItem('pnlAdsQ4Token') || '';
  }

  function tokenEmail() {
    const token = seasonToken();
    if (!token || !token.includes('.')) return '';
    try {
      const encoded = token.split('.')[0].replace(/-/g, '+').replace(/_/g, '/');
      const padded = encoded + '='.repeat((4 - encoded.length % 4) % 4);
      const bytes = Uint8Array.from(atob(padded), c => c.charCodeAt(0));
      const payload = new TextDecoder().decode(bytes);
      return (payload.split('|')[0] || '').trim().toLowerCase();
    } catch (_) {
      return '';
    }
  }

  function guideUnlocked() {
    return Boolean(document.getElementById('giftFab')?.classList.contains('unlocked'));
  }

  function fixExpertLive() {
    const card = document.querySelector('[data-product-card="ad_expert_live"]');
    if (card) {
      const stories = [...card.querySelectorAll('.include')].find(el => /Stories/.test(el.textContent || ''));
      if (stories) stories.textContent = '4 Stories для набора участников';
    }
    const table = document.querySelector('#compare table');
    if (table) {
      const row = [...table.querySelectorAll('tbody tr')].find(tr => {
        const first = tr.querySelector('td');
        return first && first.textContent.trim() === 'Stories';
      });
      if (row && row.children[3]) row.children[3].textContent = '4';
    }
  }

  function fixCampaignCopy() {
    const guide = document.querySelector('#guide .guide');
    if (guide) {
      const paragraph = guide.querySelector('p');
      if (paragraph) {
        paragraph.textContent = 'Карточка специалиста или бизнеса в Contact Guide внутри нашего Telegram-бота. Оформление и оплата теперь проходят здесь: выберите тариф, заполните карточку и оплатите через Mollie. При активной подписке −26% применяются автоматически.';
      }
    }

    const faq = [...document.querySelectorAll('.faq details')].find(item => {
      const summary = item.querySelector('summary');
      return summary && summary.textContent.includes('Как получить скидку');
    });
    if (faq) {
      const paragraph = faq.querySelector('p');
      if (paragraph) {
        paragraph.textContent = 'Откройте подарок и подпишитесь на обновления для рекламодателей. После этого −26% применяются ко всем форматам, включая Contact Guide. Новая цена показывается на странице до оплаты Mollie.';
      }
    }

    const giftCard = document.querySelector('#giftShell .gift-card');
    if (giftCard) {
      const paragraph = giftCard.querySelector(':scope > p');
      if (paragraph) {
        paragraph.textContent = 'Оставьте e-mail и получите −26% на все рекламные форматы, включая Contact Guide. Обычно 1 письмо в месяц, максимум 2 при отдельном важном поводе.';
      }
    }
  }

  function renderGuideDiscount() {
    const guide = document.querySelector('#guide .guide');
    if (!guide) return;
    const boxes = guide.querySelectorAll('.guide-box');
    const button = guide.querySelector('a.button');
    const active = guideUnlocked();

    if (boxes[0]) {
      const strong = boxes[0].querySelector('strong');
      const span = boxes[0].querySelector('span');
      if (strong) strong.innerHTML = active
        ? '<s style="font-size:15px;color:#78867f;font-weight:600">€9,99</s> €7,39'
        : '€9,99';
      if (span) span.innerHTML = active
        ? '1 месяц · обычная позиция<br><s>€99</s> → <b>€73,26</b> / год'
        : '1 месяц · обычная позиция<br>€99 / год';
    }

    if (boxes[1]) {
      const strong = boxes[1].querySelector('strong');
      const span = boxes[1].querySelector('span');
      if (strong) strong.innerHTML = active
        ? '<s style="font-size:15px;color:#78867f;font-weight:600">€19,99</s> €14,79'
        : '€19,99';
      if (span) span.innerHTML = active
        ? '1 месяц · фото/логотип · бейдж 🌟<br><s>€109</s> → <b>€80,66</b> / 6 мес · <s>€199</s> → <b>€147,26</b> / год'
        : '1 месяц · фото/логотип · бейдж 🌟 · выше Standard<br>€109 / 6 мес · €199 / год';
    }

    if (button) {
      button.textContent = active ? 'Оформить Contact Guide · −26% →' : 'Оформить Contact Guide →';
      button.setAttribute('href', '#guide');
      button.setAttribute('role', 'button');
    }
    updateCheckoutPrice();
  }

  function createGuideCheckout() {
    if (document.getElementById('guideCheckoutShell')) return;
    const shell = document.createElement('div');
    shell.className = 'guide-checkout-shell';
    shell.id = 'guideCheckoutShell';
    shell.setAttribute('role', 'dialog');
    shell.setAttribute('aria-modal', 'true');
    shell.setAttribute('aria-labelledby', 'guideCheckoutTitle');
    shell.innerHTML = `
      <div class="guide-checkout">
        <div class="guide-checkout-head">
          <div><div class="kicker">Contact Guide</div><h2 id="guideCheckoutTitle">Добавить карточку</h2></div>
          <button type="button" class="guide-checkout-close" aria-label="Закрыть">×</button>
        </div>
        <div class="guide-checkout-price">
          <span id="guideCheckoutPriceLabel">Standard · 1 месяц · incl. BTW</span>
          <strong id="guideCheckoutPrice">€9,99</strong>
        </div>
        <form id="guideCheckoutForm">
          <div class="guide-checkout-grid">
            <label class="guide-checkout-field full"><span>Тариф</span>
              <select name="plan" id="guidePlan" required>
                <option value="month">Standard · 1 месяц</option>
                <option value="year">Standard · 12 месяцев</option>
                <option value="month_premium">Premium · 1 месяц</option>
                <option value="6m_premium">Premium · 6 месяцев</option>
                <option value="year_premium">Premium · 12 месяцев</option>
              </select>
            </label>
            <label class="guide-checkout-field"><span>Имя / название</span><input name="name" maxlength="80" required placeholder="Например, Kova Executive"></label>
            <label class="guide-checkout-field"><span>Категория</span><input name="category" maxlength="50" required placeholder="Например, юрист"></label>
            <label class="guide-checkout-field" id="guideCityField"><span>Город</span><input name="city" maxlength="80" placeholder="Amsterdam"></label>
            <label class="guide-checkout-field"><span>E-mail для factuur</span><input name="email" id="guideInvoiceEmail" type="email" maxlength="200" autocomplete="email" required></label>
            <label class="guide-checkout-field full"><span>Короткое описание</span><textarea name="description" minlength="20" maxlength="500" required placeholder="Чем вы занимаетесь и чем можете быть полезны"></textarea></label>
            <label class="guide-checkout-field full"><span>Публичный контакт</span><input name="contact" maxlength="300" required placeholder="Сайт, Telegram, e-mail или телефон"></label>
          </div>
          <label class="guide-checkout-online"><input type="checkbox" name="online" id="guideOnlineWeb" value="1"><span>Работаю онлайн / по всей стране</span></label>
          <div class="guide-checkout-note" id="guidePremiumNote">Для Premium после оплаты мы запросим фото или логотип по e-mail перед публикацией карточки.</div>
          <label class="guide-checkout-terms"><input type="checkbox" name="terms" value="1" required><span>Я согласен(на) с <a href="/terms?lang=ru" target="_blank" rel="noopener">условиями</a> и <a href="/privacy?lang=ru" target="_blank" rel="noopener">политикой конфиденциальности</a>.</span></label>
          <div class="guide-checkout-error" id="guideCheckoutError"></div>
          <button class="button dark guide-checkout-submit" id="guideCheckoutSubmit" type="submit">Перейти к оплате Mollie</button>
        </form>
      </div>`;
    document.body.appendChild(shell);

    const plan = document.getElementById('guidePlan');
    const online = document.getElementById('guideOnlineWeb');
    plan.addEventListener('change', updateCheckoutPrice);
    online.addEventListener('change', () => {
      document.getElementById('guideCityField').style.display = online.checked ? 'none' : 'grid';
    });
    shell.querySelector('.guide-checkout-close').addEventListener('click', closeGuideCheckout);
    shell.addEventListener('click', event => {
      if (event.target === shell) closeGuideCheckout();
    });
    document.getElementById('guideCheckoutForm').addEventListener('submit', submitGuideCheckout);
  }

  function updateCheckoutPrice() {
    const select = document.getElementById('guidePlan');
    const price = document.getElementById('guideCheckoutPrice');
    const label = document.getElementById('guideCheckoutPriceLabel');
    if (!select || !price || !label) return;
    const item = PLAN_PRICES[select.value] || PLAN_PRICES.month;
    const active = guideUnlocked();
    price.innerHTML = active
      ? `<s style="font-size:14px;color:#78867f;font-weight:600">${euro(item.base)}</s> ${euro(item.sale)}`
      : euro(item.base);
    label.textContent = item.label + ' · incl. BTW' + (active ? ' · −26%' : '');
    const premium = select.value.includes('premium');
    const note = document.getElementById('guidePremiumNote');
    if (note) note.style.display = premium ? 'block' : 'none';
  }

  function openGuideCheckout(event) {
    if (event) event.preventDefault();
    createGuideCheckout();
    const email = tokenEmail();
    const input = document.getElementById('guideInvoiceEmail');
    if (input && email && !input.value) input.value = email;
    updateCheckoutPrice();
    document.getElementById('guideCheckoutShell').classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeGuideCheckout() {
    const shell = document.getElementById('guideCheckoutShell');
    if (shell) shell.classList.remove('open');
    document.body.style.overflow = '';
  }

  async function submitGuideCheckout(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const error = document.getElementById('guideCheckoutError');
    const submit = document.getElementById('guideCheckoutSubmit');
    error.classList.remove('show');

    const active = guideUnlocked();
    const subscribedEmail = tokenEmail();
    const submittedEmail = String(new FormData(form).get('email') || '').trim().toLowerCase();
    if (active && subscribedEmail && submittedEmail !== subscribedEmail) {
      error.textContent = 'Для скидки −26% укажите тот же e-mail, на который оформлена подписка: ' + subscribedEmail;
      error.classList.add('show');
      return;
    }

    const data = new FormData(form);
    data.set('token', seasonToken());
    if (!document.getElementById('guideOnlineWeb').checked) data.delete('online');

    submit.disabled = true;
    submit.textContent = 'Создаём оплату…';
    try {
      const response = await fetch('/ads/contact-guide/checkout', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
        body: new URLSearchParams([...data.entries()])
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok || !payload.checkout_url) {
        throw new Error(payload.error || 'Не удалось создать оплату Mollie.');
      }
      window.location.href = payload.checkout_url;
    } catch (err) {
      error.textContent = err.message || 'Не удалось создать оплату. Попробуйте ещё раз.';
      error.classList.add('show');
      submit.disabled = false;
      submit.textContent = 'Перейти к оплате Mollie';
    }
  }

  function bindGuideButton() {
    const button = document.querySelector('#guide .guide a.button');
    if (!button || button.dataset.webCheckoutBound === '1') return;
    button.dataset.webCheckoutBound = '1';
    button.addEventListener('click', openGuideCheckout);
  }

  function boot() {
    fixExpertLive();
    fixCampaignCopy();
    renderGuideDiscount();
    bindGuideButton();

    const giftFab = document.getElementById('giftFab');
    if (giftFab) {
      new MutationObserver(() => {
        renderGuideDiscount();
        updateCheckoutPrice();
      }).observe(giftFab, {attributes: true, attributeFilter: ['class']});
    }

    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') closeGuideCheckout();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
