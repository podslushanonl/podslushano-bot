(() => {
  const API = 'https://worker-production-ad76.up.railway.app';
  const root = document.getElementById('allo-v2');
  if (!root || root.dataset.awReady) return;
  root.dataset.awReady = '1';
  const $ = selector => root.querySelector(selector);
  const node = (tag, className, value) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = value;
    return element;
  };
  const euro = cents => new Intl.NumberFormat('nl-NL', {style:'currency', currency:'EUR'}).format(cents / 100);
  const date = value => new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'long', timeZone:'Europe/Amsterdam'}).format(new Date(value));
  const month = value => new Intl.DateTimeFormat('ru-RU', {month:'long', year:'numeric', timeZone:'Europe/Amsterdam'}).format(new Date(value));
  const scrollTo = element => element.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'nearest'});
  const error = (form, message) => { form.querySelector('.aw-form-error').textContent = message; };
  const post = async (path, body) => {
    const response = await fetch(API + path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Не удалось оформить заказ. Повторите попытку.');
    return data;
  };
  const result = data => {
    if (data.checkout_url) { location.href = data.checkout_url; return; }
    if (data.status === 'paid') {
      const box = $('#aw-order-status');
      box.hidden = false;
      box.textContent = 'Место подтверждено. Детали придут на вашу почту.';
      scrollTo(box);
    }
  };
  const category = {city:'Город', nature:'Природа', special:'Особый день'};
  function eventCard(event) {
    const details = node('details','aw-event');
    details.dataset.eventKey = event.key;
    const summary = node('summary');
    const thumb = node('img','aw-event-thumb');
    thumb.src = event.photos[0].url;
    thumb.alt = event.photos[0].alt;
    thumb.loading = 'lazy';
    const head = node('span','aw-event-head');
    head.append(node('small','',((category[event.category] || 'Прогулка') + ' · ' + date(event.starts_at))), node('strong','',event.title), node('em','',event.place));
    const price = node('span','aw-event-price');
    price.append(document.createTextNode(euro(event.price_cents)), node('small','',event.inventory.available ? event.inventory.available + ' мест свободно' : 'Мест нет'));
    price.dataset.available = event.key;
    const arrow = node('span','aw-event-arrow','+');
    arrow.setAttribute('aria-hidden','true');
    summary.append(thumb,head,price,arrow);
    details.append(summary);

    const body = node('div','aw-event-body');
    const gallery = node('div','aw-gallery');
    const track = node('div','aw-gallery-track');
    event.photos.forEach(photo => {
      const figure = node('figure');
      const image = node('img');
      image.src = photo.url; image.alt = photo.alt; image.loading = 'lazy';
      figure.append(image);
      if (photo.caption) figure.append(node('figcaption','',photo.caption));
      track.append(figure);
    });
    gallery.append(track);
    if (event.photos.length > 1) {
      const controls = node('div','aw-gallery-controls');
      let index = 0;
      const count = node('span','',`1 / ${event.photos.length}`);
      const move = delta => {
        index = (index + delta + event.photos.length) % event.photos.length;
        track.children[index].scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'nearest',inline:'start'});
        count.textContent = `${index + 1} / ${event.photos.length}`;
      };
      const prev = node('button','','←'); prev.type='button'; prev.setAttribute('aria-label','Предыдущее фото'); prev.onclick=()=>move(-1);
      const next = node('button','','→'); next.type='button'; next.setAttribute('aria-label','Следующее фото'); next.onclick=()=>move(1);
      controls.append(prev,count,next); gallery.append(controls);
    }
    const info = node('div','aw-event-info');
    const facts = node('div','aw-event-facts');
    [['Время',event.duration],['Точка встречи',event.meeting],['Места',`${event.inventory.paid} оплачено · ${event.inventory.available} свободно`]].forEach(([label,value]) => {
      const item = node('div'); item.append(node('small','',label),node('strong','',value)); facts.append(item);
    });
    facts.dataset.facts = event.key;
    info.append(facts,node('p','aw-event-intro',event.intro));
    const columns = node('div','aw-event-columns');
    const route = node('div'); route.append(node('h4','','Как пройдёт день'));
    const ordered = node('ol'); event.route.forEach(value=>ordered.append(node('li','',value))); route.append(ordered);
    const terms = node('div');
    [['Входит в стоимость',event.included],['Оплачивается отдельно',event.extra]].forEach(([label,items])=>{
      if (!items.length) return;
      terms.append(node('h4','',label));
      const list = node('ul'); items.forEach(value=>list.append(node('li','',value))); terms.append(list);
    });
    columns.append(route,terms); info.append(columns);
    const open = node('button','aw-button aw-book-button','Оформить место ↗');
    open.type='button';
    open.hidden = event.inventory.available < 1;
    const panel = node('div','aw-book-panel'); panel.hidden=true;
    panel.append(node('h3','','Ваше место на прогулке'),node('p','','Введите данные участника. Код прежнего абонемента действует для городских и природных прогулок.'));
    const form = node('form','aw-form');
    form.innerHTML = '<label class="aw-field">Имя<input name="name" autocomplete="name" required></label><label class="aw-field">Электронная почта<input name="email" type="email" autocomplete="email" required></label><label class="aw-field aw-full">Код абонемента или сертификата<input name="code" autocomplete="off"></label><label class="aw-check aw-full"><input name="agreed" type="checkbox" required><span>Согласен(на) на обработку данных для заказа. <a href="https://worker-production-ad76.up.railway.app/privacy" target="_blank" rel="noopener">Политика конфиденциальности</a>.</span></label><p class="aw-form-error aw-full" aria-live="polite"></p><button class="aw-button aw-full" type="submit">Продолжить оформление <span aria-hidden="true">↗</span></button>';
    form.addEventListener('submit',async e=>{
      e.preventDefault();
      const button=form.querySelector('button[type=submit]'); button.disabled=true; error(form,'');
      try {
        const values=new FormData(form);
        result(await post('/api/allo/v2/book',{event_key:event.key,name:values.get('name'),email:values.get('email'),code:values.get('code'),agreed:values.get('agreed')==='on'}));
      } catch (problem) { error(form,problem.message); } finally { button.disabled=false; }
    });
    panel.append(form);
    open.onclick=()=>{panel.hidden=!panel.hidden;if(!panel.hidden)scrollTo(panel)};
    info.append(open,panel); body.append(gallery,info); details.append(body);
    return details;
  }
  const eventsList = $('#aw-events');
  let loaded = false;
  async function refresh() {
    try {
      const response = await fetch(API + '/api/allo/v2/events', {cache:'no-store'});
      if (!response.ok) throw Error('catalog');
      const data = await response.json();
      if (!loaded) {
        loaded = true;
        if (data.events.length) {
          $('#aw-dates').hidden = false;
          root.querySelectorAll('.aw-dates-link').forEach(link=>link.hidden=false);
          [['#aw-hero-cta','Выбрать прогулку ↗'],['#aw-header-cta','Выбрать прогулку ↗']].forEach(([selector,label])=>{
            const link=$(selector); link.href='#aw-dates'; link.textContent=label;
          });
          let currentMonth = '';
          data.events.forEach(event=>{
            const key=event.starts_at.slice(0,7);
            if (key!==currentMonth) {currentMonth=key;eventsList.append(node('div','aw-month',month(event.starts_at)));}
            eventsList.append(eventCard(event));
          });
        }
        if (data.gift_amounts_cents.length) {
          $('#aw-gifts').hidden=false;
          const amounts=$('#aw-amounts');
          data.gift_amounts_cents.forEach((value,index)=>{
            const label=node('label'); const input=node('input');
            input.type='radio'; input.name='amount_cents'; input.value=value; input.required=true;
            if (!index) input.checked=true;
            label.append(input,node('span','',euro(value))); amounts.append(label);
          });
        }
      } else {
        data.events.forEach(event=>{
          const item=[...eventsList.querySelectorAll('[data-available]')].find(x=>x.dataset.available===event.key);
          if (item) item.querySelector('small').textContent=event.inventory.available ? event.inventory.available+' мест свободно' : 'Мест нет';
          const card=[...eventsList.querySelectorAll('[data-event-key]')].find(x=>x.dataset.eventKey===event.key);
          if (card) {
            const facts=card.querySelector('[data-facts]');
            facts.lastChild.querySelector('strong').textContent=`${event.inventory.paid} оплачено · ${event.inventory.available} свободно`;
            const button=card.querySelector('.aw-book-button');
            button.hidden=event.inventory.available<1;
            if (event.inventory.available<1) card.querySelector('.aw-book-panel').hidden=true;
          }
        });
      }
      $('#aw-update-error').hidden=true;
    } catch (_) {
      if (loaded) $('#aw-update-error').hidden=false;
    }
  }
  const giftForm=$('#aw-gift-form');
  giftForm.querySelector('[name=for_self]').addEventListener('change',e=>{
    giftForm.querySelectorAll('.aw-recipient').forEach(field=>{
      field.hidden=e.target.checked; field.querySelector('input').required=!e.target.checked;
    });
  });
  giftForm.addEventListener('submit',async e=>{
    e.preventDefault();
    const button=giftForm.querySelector('button[type=submit]'); button.disabled=true; error(giftForm,'');
    try {
      const values=new FormData(giftForm), self=values.get('for_self')==='on';
      result(await post('/api/allo/v2/gift',{amount_cents:Number(values.get('amount_cents')),name:values.get('name'),email:values.get('email'),recipient_name:self?values.get('name'):values.get('recipient_name'),recipient_email:self?values.get('email'):values.get('recipient_email'),message:values.get('message'),agreed:values.get('agreed')==='on'}));
    } catch (problem) { error(giftForm,problem.message); } finally { button.disabled=false; }
  });
  const token=new URLSearchParams(location.search).get('allo_order');
  if (token) {
    const box=$('#aw-order-status'); box.hidden=false; box.textContent='Проверяем оплату…';
    const poll=async attempt=>{
      try {
        const response=await fetch(API+'/api/allo/v2/orders/'+encodeURIComponent(token),{cache:'no-store'});
        if (!response.ok) throw Error('order');
        const data=await response.json();
        box.textContent=data.status==='paid'
          ? (data.kind==='gift'
             ? (data.email_sent?'Сертификат оплачен и отправлен получателю на почту.':'Сертификат оплачен. Готовим письмо получателю.')
             : (data.email_sent?'Место подтверждено. Детали отправлены на вашу почту.':'Место подтверждено. Готовим письмо с деталями.'))
          : data.status==='refund_requested'?'Оплата получена, но место требует проверки. Мы свяжемся с вами для возврата.'
          : data.status==='canceled'?'Оплата не завершена. Место не забронировано.'
          : 'Платёж ещё обрабатывается. Обновите страницу через минуту.';
        if ((data.status==='pending'||(data.status==='paid'&&!data.email_sent))&&attempt<7) setTimeout(()=>poll(attempt+1),3000);
      } catch (_) {box.textContent='Не удалось проверить заказ. Обновите страницу.';}
    };
    poll(0);
    scrollTo(box);
  }
  refresh();
  setInterval(refresh,30000);
})();
