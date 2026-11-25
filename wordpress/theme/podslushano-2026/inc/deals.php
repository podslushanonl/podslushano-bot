<?php
/** ВЫГОДНО В NL — independent paid membership, direct Mollie via WordPress.
 * Launch gate intentionally closed until delivery/access integration is verified.
 */
if (!defined('ABSPATH')) exit;

const PN_DEALS_PRICE_CENTS = 399;
function pn_deals_ready() {
    return defined('PN_DEALS_ENABLE') && PN_DEALS_ENABLE === true
        && has_filter('pn_deals_entitlement_event')
        && apply_filters('pn_deals_access_ready', false) === true
        && preg_match('/^live_[A-Za-z0-9]+$/D', pn_donation_key());
}
function pn_deals_record_key($id) { return 'pn_deals_first_' . $id; }
function pn_deals_price() { return pn_svoi_amount(PN_DEALS_PRICE_CENTS); }
function pn_deals_url() { return add_query_arg('pn_deals', '1', home_url('/')); }
function pn_deals_error($message, $status = 400) {
    return new WP_REST_Response(['ok' => false, 'error' => $message], $status);
}
function pn_deals_checkout($request) {
    if (!pn_deals_ready()) return pn_deals_error('Подписка пока не открыта.', 503);
    $b = $request->get_json_params();
    $email = is_array($b) && is_string($b['email'] ?? null) ? trim($b['email']) : '';
    if (!is_email($email) || strlen($email) > 200) return pn_deals_error('Проверьте электронную почту.');
    if (($b['consent'] ?? null) !== true) return pn_deals_error('Подтвердите ежемесячное списание.');
    $rate = 'pn_deals_rate_' . hash('sha256', ($_SERVER['REMOTE_ADDR'] ?? '') . '|' . wp_salt('nonce'));
    $n = (int)get_transient($rate);
    if ($n >= 5) return pn_deals_error('Повторите через минуту.', 429);
    set_transient($rate, $n + 1, 60);
    // Price is owned by the server, not the widget. Separate product metadata and webhook.
    $customer = pn_svoi_api('POST', '/v2/customers', ['name'=>$email,'email'=>$email]);
    if (is_wp_error($customer) || !preg_match('/^cst_[A-Za-z0-9]+$/D', $customer['id'] ?? ''))
        return pn_deals_error('Не удалось открыть оплату.', 502);
    $cid = $customer['id'];
    $payment = pn_svoi_api('POST', '/v2/payments', [
        'amount'=>['currency'=>'EUR','value'=>pn_deals_price()],
        'description'=>'Vygodno NL - maandabonnement',
        'customerId'=>$cid,'sequenceType'=>'first',
        'redirectUrl'=>add_query_arg('checkout','return',pn_deals_url()),
        'webhookUrl'=>rest_url('pn/v1/deals/webhook'),
        'metadata'=>['kind'=>'deals_first','source'=>'deals_wp'],
    ]);
    if (is_wp_error($payment) || !preg_match('/^tr_[A-Za-z0-9]+$/D', $payment['id'] ?? ''))
        return pn_deals_error('Не удалось открыть оплату.',502);
    $id = $payment['id'];
    $url = $payment['_links']['checkout']['href'] ?? '';
    $u = wp_parse_url($url);
    if (($u['scheme'] ?? '') !== 'https' || !preg_match('/(^|\.)mollie\.com$/iD',$u['host'] ?? ''))
        return pn_deals_error('Некорректный адрес оплаты.',502);
    // Do not expose a checkout until its local record exists.
    if (!add_option(pn_deals_record_key($id),[
        'email'=>$email,'customer'=>$cid,'cents'=>PN_DEALS_PRICE_CENTS,'consent_at'=>gmdate('c'),
        'status'=>'pending','created_at'=>time()
    ],'',false)) return pn_deals_error('Не удалось сохранить заявку.',503);
    wp_schedule_single_event(time()+300,'pn_deals_retry',[$id]);
    return new WP_REST_Response(['ok'=>true,'checkout_url'=>$url],200);
}
function pn_deals_cancel_url($id) {
    return add_query_arg(['action'=>'pn_deals_cancel','payment'=>$id,
        'token'=>hash_hmac('sha256','deals-cancel:'.$id,wp_salt('auth'))],admin_url('admin-post.php'));
}
function pn_deals_valid_payment($p,$r,$first) {
    if (($p['mode']??'')!=='live' || ($p['customerId']??'')!==$r['customer']
        || ($p['amount']['currency']??'')!=='EUR'
        || pn_donation_cents($p['amount']['value']??'') !== (int)$r['cents']) return false;
    if ($first) return ($p['sequenceType']??'')==='first' && ($p['metadata']['kind']??'')==='deals_first'
        && ($p['metadata']['source']??'')==='deals_wp';
    return ($p['sequenceType']??'')==='recurring' && ($p['metadata']['kind']??'')==='deals_renewal'
        && ($p['metadata']['source']??'')==='deals_wp'
        && !empty($r['subscription']) && ($p['subscriptionId']??'')===$r['subscription'];
}
function pn_deals_subscription($id,$p,$r) {
    $path='/v2/customers/'.$r['customer'].'/subscriptions';
    $list=pn_svoi_api('GET',$path.'?limit=250');
    if (is_wp_error($list)||!is_array($list['_embedded']['subscriptions']??null)||!empty($list['_links']['next'])) return false;
    $all=$list['_embedded']['subscriptions'];
    $matches=array_values(array_filter($all,function($s)use($id){
        return ($s['metadata']['kind']??'')==='deals_renewal' && ($s['metadata']['first_payment_id']??'')===$id;
    }));
    if (count($matches)===1) $sub=$matches[0];
    elseif (count($all)!==0) return false;
    else {
        $start=pn_svoi_next_date($p['paidAt']??'');
        if (!$start||$start<gmdate('Y-m-d')) return false; // never backcharge
        $sub=pn_svoi_api('POST',$path,[
            'amount'=>['currency'=>'EUR','value'=>pn_svoi_amount($r['cents'])],
            'interval'=>'1 month','startDate'=>$start,'description'=>'Vygodno NL - maandabonnement',
            'webhookUrl'=>rest_url('pn/v1/deals/webhook'),
            'metadata'=>['kind'=>'deals_renewal','source'=>'deals_wp','first_payment_id'=>$id],
        ],hash('sha256','deals-wp:'.$id));
    }
    if (is_wp_error($sub)||!preg_match('/^sub_[A-Za-z0-9]+$/D',$sub['id']??'')
        ||($sub['amount']['currency']??'')!=='EUR'||($sub['amount']['value']??'')!==pn_svoi_amount($r['cents'])
        ||($sub['interval']??'')!=='1 month'||in_array($sub['status']??'', ['canceled','completed'],true)) return false;
    return $sub['id'];
}
function pn_deals_process($pid) {
    if (!is_string($pid)||!preg_match('/^tr_[A-Za-z0-9]+$/D',$pid)) return true;
    $p=pn_svoi_api('GET','/v2/payments/'.$pid);
    if (is_wp_error($p)) return false;
    $kind=$p['metadata']['kind']??'';
    if (($p['id']??'')!==$pid || ($p['metadata']['source']??'')!=='deals_wp') return true;
    if (!in_array($kind,['deals_first','deals_renewal'],true)) return true;
    $first=$kind==='deals_first'; $id=$first?$pid:($p['metadata']['first_payment_id']??'');
    if (!preg_match('/^tr_[A-Za-z0-9]+$/D',$id)) return true;
    global $wpdb;
    $lock='pn_deals_'.substr(hash('sha256',$wpdb->prefix.$id),0,48);
    if ((int)$wpdb->get_var($wpdb->prepare('SELECT GET_LOCK(%s, 0)',$lock))!==1) return false;
    try {
        $rk=pn_deals_record_key($id); wp_cache_delete($rk,'options');
        $r=get_option($rk);
        if (!is_array($r)) return true;
        if (!pn_deals_valid_payment($p,$r,$first)) return false;
        $status=$p['status']??'';
        if (in_array($status,['open','pending','authorized'],true)) return false;
        if ($first && in_array($status,['failed','canceled','expired'],true) && $r['status']==='pending') {
            $r['status']='closed'; update_option($rk,$r,false); return true;
        }
        $net=pn_donation_net($p); 
        $event=$status==='paid'&&$net===(int)$r['cents']?'paid':($status==='paid'?'reversal':$status);
        // Persist and deliver each distinct state; delivery integration must be idempotent by event_id.
        $event_id=hash('sha256',$pid.':'.$event.':'.$net);
        $event_key='pn_deals_event_'.$event_id;
        if (get_option($event_key)) return true;
        if ($first && $event==='paid' && empty($r['subscription'])) {
            if ($r['status']!=='pending'||empty($r['consent_at'])) return false;
            $sub=pn_deals_subscription($id,$p,$r);
            if (!$sub) return false;
            $r['subscription']=$sub; $r['status']='subscribed';
            update_option($rk,$r,false);
        }
        $payload=['event_id'=>$event_id,'kind'=>$event,'first_payment_id'=>$id,'payment_id'=>$pid,
            'customer_id'=>$r['customer'],'subscription_id'=>$r['subscription']??'','email'=>$r['email'],
            'paid_at'=>$p['paidAt']??'','created_at'=>$p['createdAt']??'','net_cents'=>$net,
            'price_cents'=>(int)$r['cents'],'cancel_url'=>pn_deals_cancel_url($id)];
        // No fabricated entitlement. Missing/failed delivery must retry.
        if (apply_filters('pn_deals_entitlement_event',false,$payload)!==true) return false;
        add_option($event_key,gmdate('c'),'',false);
        return true;
    } finally { $wpdb->get_var($wpdb->prepare('SELECT RELEASE_LOCK(%s)',$lock)); }
}
function pn_deals_retry($id) {
    if (pn_deals_process($id)) return;
    $rk='pn_deals_retry_count_'.hash('sha256',$id);
    $n=(int)get_option($rk,0)+1;
    update_option($rk,$n,false);
    if ($n<=24) wp_schedule_single_event(time()+min(3600,300*$n),'pn_deals_retry',[$id]);
    else error_log('Vygodno NL payment needs reconciliation: '.$id);
}
add_action('pn_deals_retry','pn_deals_retry');
function pn_deals_webhook($request) {
    $id=$request->get_param('id');
    if (!is_string($id)||!preg_match('/^tr_[A-Za-z0-9]+$/D',$id)) return new WP_REST_Response(['ok'=>true],200);
    $ok=pn_deals_process($id);
    if (!$ok && !wp_next_scheduled('pn_deals_retry',[$id])) wp_schedule_single_event(time()+300,'pn_deals_retry',[$id]);
    return new WP_REST_Response(['ok'=>$ok],$ok?200:503);
}
function pn_deals_cancel() {
    $id=sanitize_text_field(wp_unslash($_GET['payment']??'')); $t=sanitize_text_field(wp_unslash($_GET['token']??''));
    if (!preg_match('/^tr_[A-Za-z0-9]+$/D',$id)||!hash_equals(hash_hmac('sha256','deals-cancel:'.$id,wp_salt('auth')),$t))
        wp_die('Ссылка недействительна. Напишите нам на podslushano.nl@gmail.com.','Отмена',['response'=>403]);
    $r=get_option(pn_deals_record_key($id));
    if (!is_array($r)||empty($r['subscription'])) wp_die('Подписка не найдена. Напишите нам.','Отмена',['response'=>404]);
    nocache_headers();
    if ($_SERVER['REQUEST_METHOD']!=='POST') {
        echo '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Отмена подписки</title><main style="max-width:520px;margin:50px auto;font:18px system-ui;padding:20px"><h1>Отменить продление?</h1><p>Доступ сохраняется до конца оплаченного периода. Следующих списаний не будет.</p><form method="post" action="'.esc_url(pn_deals_cancel_url($id)).'"><button type="submit">Отменить продление</button></form></main>'; exit;
    }
    global $wpdb;
    $lock='pn_deals_'.substr(hash('sha256',$wpdb->prefix.$id),0,48);
    if ((int)$wpdb->get_var($wpdb->prepare('SELECT GET_LOCK(%s, 0)',$lock))!==1) wp_die('Повторите чуть позже.','Отмена',['response'=>503]);
    $ok=false;
    try {
        $rk=pn_deals_record_key($id); wp_cache_delete($rk,'options'); $r=get_option($rk);
        if ($r['status']==='cancelled') $ok=true;
        else {
            $path='/v2/customers/'.$r['customer'].'/subscriptions/'.$r['subscription'];
            $result=pn_svoi_api('DELETE',$path);
            if (is_wp_error($result)) {
                $s=pn_svoi_api('GET',$path);
                if (!is_wp_error($s)&&($s['status']??'')==='canceled') $result=$s;
            }
            if (!is_wp_error($result)) { $r['status']='cancelled'; update_option($rk,$r,false); $ok=true; }
        }
    } finally { $wpdb->get_var($wpdb->prepare('SELECT RELEASE_LOCK(%s)',$lock)); }
    wp_die($ok?'Автоматическое продление отменено. Доступ действует до конца оплаченного периода.':'Не удалось отменить подписку. Напишите нам на podslushano.nl@gmail.com.','Выгодно в NL',['response'=>$ok?200:503]);
}
add_action('admin_post_nopriv_pn_deals_cancel','pn_deals_cancel');
add_action('admin_post_pn_deals_cancel','pn_deals_cancel');
add_action('rest_api_init',function(){
    register_rest_route('pn/v1','/deals/checkout',['methods'=>'POST','permission_callback'=>'__return_true','callback'=>'pn_deals_checkout']);
    register_rest_route('pn/v1','/deals/webhook',['methods'=>'POST','permission_callback'=>'__return_true','callback'=>'pn_deals_webhook']);
});
function pn_deals_widget($atts=[]) {
    $enabled=pn_deals_ready()&&!is_admin();
    $id=wp_unique_id('pn-deals-');
    ob_start(); ?>
    <section class="pn-deals-widget" id="<?php echo esc_attr($id); ?>" data-url="<?php echo esc_url(rest_url('pn/v1/deals/checkout')); ?>" data-enabled="<?php echo $enabled?'1':'0'; ?>">
      <style>
       .pn-deals-widget{--pd-orange:#f28c28;--pd-ink:#181818;--pd-paper:#fffaf3;box-sizing:border-box;max-width:1040px;margin:24px auto;font-family:Mont,Inter,system-ui,sans-serif;color:var(--pd-ink);background:var(--pd-paper);border:1px solid #e8e1d8;border-radius:32px;padding:clamp(22px,5vw,52px)}
       .pn-deals-widget *{box-sizing:border-box}.pd-top{display:flex;align-items:center;gap:10px;font-size:13px;font-weight:750;letter-spacing:.08em;text-transform:uppercase}.pd-dot{width:10px;height:10px;border-radius:50%;background:var(--pd-orange)}.pd-layout{display:grid;grid-template-columns:1.1fr 1fr;gap:clamp(22px,4vw,50px);align-items:center}.pd-title{font-size:clamp(42px,7vw,78px);line-height:.93;letter-spacing:-.065em;margin:25px 0 20px;font-weight:900}.pd-title span{color:var(--pd-orange)}.pd-lead{font-size:19px;line-height:1.5;max-width:36ch}.pd-features{display:grid;gap:12px;margin:24px 0;padding:0;list-style:none}.pd-features li{display:flex;align-items:center;gap:10px;font-size:15px}.pd-features li:before{content:"✓";background:#f7e5d1;border-radius:50%;display:grid;place-items:center;width:26px;height:26px;flex:none;font-weight:800}.pd-form{background:#fff;border:1px solid #eee7df;border-radius:26px;padding:26px;box-shadow:0 18px 50px -38px #21170d88;display:grid;gap:15px}.pd-price{font-size:52px;line-height:1;letter-spacing:-.06em;font-weight:850}.pd-price small{font-size:16px;letter-spacing:0;font-weight:500;color:#666}.pd-label{display:grid;gap:7px;font-size:14px;font-weight:600}.pd-email{width:100%;padding:14px;border-radius:14px;border:1px solid #ded8d1;font:inherit;background:white;color:#181818}.pd-consent{display:flex;gap:10px;align-items:flex-start;font-size:12px;line-height:1.5;color:#4e4b47}.pd-consent input{width:18px;height:18px;flex:none;accent-color:var(--pd-orange)}.pd-pay{border:0;border-radius:17px;padding:16px;background:var(--pd-orange);color:#161616;font-size:16px;font-weight:800;cursor:pointer}.pd-pay:disabled{cursor:not-allowed;opacity:.55}.pd-small{font-size:12px;color:#666;line-height:1.45;margin:0}.pd-status{font-size:13px;line-height:1.4}.pd-brand{font-size:12px;letter-spacing:.03em;margin-top:24px;color:#666}.pd-form a{color:inherit;text-decoration:underline}@media(max-width:700px){.pd-layout{grid-template-columns:1fr}.pn-deals-widget{border-radius:24px}.pd-form{padding:20px}.pd-title{margin-top:20px}}
      </style>
      <div class="pd-top"><span class="pd-dot"></span> Закрытый канал · Нидерланды</div>
      <div class="pd-layout">
       <div><h1 class="pd-title">ВЫГОДНО<br>В <span>NL.</span></h1>
        <p class="pd-lead">Меньше времени на поиск скидок. Больше денег на то, что вам действительно нужно.</p>
        <ul class="pd-features"><li>Проверенные акции супермаркетов</li><li>Купоны, кешбэк и бесплатные находки</li><li>Выгодные предложения для дома и досуга</li></ul>
        <div class="pd-brand">Проект podslushano.nl</div></div>
       <form class="pd-form">
        <div><strong>Ежемесячный доступ</strong><div class="pd-price">€3,99 <small>/ месяц</small></div></div>
        <p class="pd-small">Первый платёж при оформлении, далее — €3,99 каждый месяц до отмены.</p>
        <label class="pd-label">Электронная почта<input class="pd-email" type="email" name="email" autocomplete="email" required placeholder="name@email.nl"></label>
        <label class="pd-consent"><input name="consent" type="checkbox" required>Я согласен(-на) на ежемесячное списание €3,99 до отмены подписки. Доступ сохраняется до конца оплаченного периода.</label>
        <button class="pd-pay" type="submit" <?php disabled(!$enabled); ?>><?php echo $enabled?'Оформить подписку · €3,99':'Подписка скоро откроется'; ?></button>
        <p class="pd-small">Оплата через Mollie. Ссылка для управления подпиской придёт на почту. <a href="<?php echo esc_url(home_url('/privacy-statement-eu/')); ?>">Политика конфиденциальности</a>.</p>
        <div class="pd-status" role="status" aria-live="polite"><?php echo $enabled?'':'Пилотный режим. Оплата пока отключена.'; ?></div>
       </form>
      </div>
      <script data-category="functional">
      (()=>{const root=document.getElementById(<?php echo wp_json_encode($id); ?>);if(!root)return;const form=root.querySelector('form'),btn=form.querySelector('button'),status=form.querySelector('.pd-status');form.addEventListener('submit',async e=>{e.preventDefault();if(root.dataset.enabled!=='1'||btn.disabled)return;btn.disabled=true;status.textContent='Открываем защищённую оплату…';try{const res=await fetch(root.dataset.url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:form.email.value.trim(),consent:form.consent.checked})});const j=await res.json();if(!res.ok||!j.ok||!j.checkout_url)throw Error(j.error||'Оплата временно недоступна.');const u=new URL(j.checkout_url);if(u.protocol!=='https:'||!/(^|\.)mollie\.com$/i.test(u.hostname))throw Error('Некорректный адрес оплаты.');location.assign(u.href)}catch(err){status.textContent=err.message;btn.disabled=false}})})();
      </script>
    </section>
    <?php return ob_get_clean();
}
add_shortcode('pn_deals','pn_deals_widget');
add_action('template_redirect',function(){
    if (($_GET['pn_deals']??'')!=='1') return;
    // Private owner preview until paid access is ready. Return view never claims payment is confirmed.
    if (!pn_deals_ready()&&!current_user_can('manage_options')) { status_header(404); nocache_headers(); exit; }
    nocache_headers(); header('X-Robots-Tag: noindex, nofollow',true);
    ?><!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Выгодно в NL · podslushano.nl</title></head><body style="margin:0;padding:12px;background:#f5f2ee;font-family:system-ui,sans-serif"><?php
    if (($_GET['checkout']??'')==='return') echo '<p role="status" style="max-width:1040px;margin:20px auto">Платёж проверяется. Подтверждение и инструкции придут на вашу электронную почту после успешной оплаты.</p>';
    echo pn_deals_widget(); ?><p style="text-align:center"><a href="<?php echo esc_url(home_url('/')); ?>">На главную podslushano.nl</a></p></body></html><?php exit;
},0);
add_action('admin_menu',function(){
    add_submenu_page('options-general.php','Выгодно в NL','Выгодно в NL','manage_options','pn-deals-preview',function(){
        echo '<div class="wrap"><h1>Выгодно в NL — предпросмотр</h1><p>Запуск заблокирован до подключения выдачи доступа. Для страницы: шорткод <code>[pn_deals]</code>.</p>'.pn_deals_widget().'</div>';
    });
});
