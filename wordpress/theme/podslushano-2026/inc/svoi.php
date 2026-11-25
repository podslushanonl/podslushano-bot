<?php
/** Native WordPress checkout for new Svoi contributions. Existing Railway subscriptions untouched. */
if (!defined('ABSPATH')) exit;

function pn_svoi_api($method, $path, $body = null, $key = '') {
    if (!preg_match('#^/v2/(?:payments(?:/tr_[A-Za-z0-9]+)?|customers(?:/cst_[A-Za-z0-9]+/(?:subscriptions(?:/sub_[A-Za-z0-9]+)?|mandates)(?:\?limit=250)?)?)$#D', $path))
        return new WP_Error('svoi_path', 'Недопустимый путь Mollie.');
    if (!preg_match('/^live_[A-Za-z0-9]+$/D', pn_donation_key())) return new WP_Error('svoi_key', 'Оплата временно недоступна.');
    $headers = ['Authorization' => 'Bearer ' . pn_donation_key(), 'Accept' => 'application/json'];
    if ($key) $headers['Idempotency-Key'] = $key;
    $args = ['method' => $method, 'headers' => $headers, 'timeout' => 15, 'redirection' => 0];
    if ($body !== null) {
        $args['headers']['Content-Type'] = 'application/json';
        $args['body'] = wp_json_encode($body);
    }
    $res = wp_remote_request('https://api.mollie.com' . $path, $args);
    if (is_wp_error($res)) return new WP_Error('svoi_network', 'Mollie временно недоступен.');
    $status = wp_remote_retrieve_response_code($res);
    if ($status === 204) return [];
    $data = json_decode(wp_remote_retrieve_body($res), true);
    if ($status < 200 || $status >= 300 || !is_array($data)) return new WP_Error('svoi_api', 'Не удалось выполнить операцию Mollie.');
    return $data;
}
function pn_svoi_error($message, $status = 400) {
    return new WP_REST_Response(['ok' => false, 'error' => $message], $status);
}
function pn_svoi_amount($cents) {
    return sprintf('%d.%02d', intdiv($cents, 100), $cents % 100);
}
function pn_svoi_next_date($paid) {
    try {
        $date = new DateTimeImmutable($paid, new DateTimeZone('UTC'));
        $next = $date->modify('first day of next month');
        return $next->setDate((int)$next->format('Y'), (int)$next->format('m'), min((int)$date->format('d'), (int)$next->format('t')))->format('Y-m-d');
    } catch (Exception $e) { return ''; }
}
function pn_svoi_record_key($id) { return 'pn_svoi_payment_' . $id; }
function pn_svoi_checkout($request) {
    $b = $request->get_json_params();
    if (!is_array($b)) return pn_svoi_error('Проверьте данные.');
    $monthly = ($b['monthly'] ?? false) === true;
    $cents = $b['amount_cents'] ?? null;
    $mail = is_string($b['email'] ?? null) ? trim($b['email']) : '';
    if (!is_int($cents) || $cents < ($monthly ? 200 : 100) || $cents > 100000) return pn_svoi_error('Укажите допустимую сумму.');
    if (($mail !== '' && !is_email($mail)) || strlen($mail) > 200 || ($monthly && !$mail)) return pn_svoi_error('Укажите корректную электронную почту.');
    if ($monthly && ($b['consent'] ?? false) !== true) return pn_svoi_error('Подтвердите ежемесячное списание.');
    // Limit anonymous checkout creation; no forwarded headers trusted.
    $rate = 'pn_svoi_rate_' . hash('sha256', ($_SERVER['REMOTE_ADDR'] ?? '') . '|' . wp_salt('nonce'));
    $n = (int)get_transient($rate);
    if ($n >= 15) return pn_svoi_error('Слишком много запросов. Попробуйте через минуту.', 429);
    set_transient($rate, $n + 1, 60);
    $amount = ['currency' => 'EUR', 'value' => pn_svoi_amount($cents)];
    $meta = ['kind' => 'donation', 'source' => 'svoi_wp', 'monthly' => $monthly];
    $body = ['amount' => $amount, 'description' => $monthly ? 'Maandelijkse bijdrage podslushano.nl' : 'Bijdrage podslushano.nl',
        'redirectUrl' => home_url('/?donation=thanks'), 'webhookUrl' => rest_url('pn/v1/svoi/webhook'), 'metadata' => $meta];
    $customer = '';
    if ($monthly) {
        $c = pn_svoi_api('POST', '/v2/customers', ['name' => $mail, 'email' => $mail]);
        if (is_wp_error($c) || !preg_match('/^cst_[A-Za-z0-9]+$/D', $c['id'] ?? '')) return pn_svoi_error('Не удалось открыть оплату.', 502);
        $customer = $c['id']; $body['customerId'] = $customer; $body['sequenceType'] = 'first';
    }
    $p = pn_svoi_api('POST', '/v2/payments', $body);
    if (is_wp_error($p) || !preg_match('/^tr_[A-Za-z0-9]+$/D', $p['id'] ?? '')) return pn_svoi_error('Не удалось открыть оплату.', 502);
    $url = $p['_links']['checkout']['href'] ?? '';
    $u = wp_parse_url($url);
    if (($u['scheme'] ?? '') !== 'https' || !preg_match('/(^|\.)mollie\.com$/iD', $u['host'] ?? '')) return pn_svoi_error('Некорректный адрес оплаты.', 502);
    $id = $p['id'];
    // Persist the original authorization BEFORE exposing checkout.
    if (!add_option(pn_svoi_record_key($id), ['customer' => $customer, 'email' => $mail, 'cents' => $cents, 'monthly' => $monthly,
        'consent_at' => $monthly ? gmdate('c') : '', 'created_at' => time(), 'status' => 'pending'], '', false))
        return pn_svoi_error('Не удалось сохранить заявку.', 503);
    wp_schedule_single_event(time() + 300, 'pn_svoi_retry', [$id]);
    return new WP_REST_Response(['ok' => true, 'checkout_url' => $url], 200);
}
function pn_svoi_link($id) {
    return add_query_arg(['action' => 'pn_svoi_cancel', 'payment' => $id,
        'token' => hash_hmac('sha256', 'svoi-cancel:' . $id, wp_salt('auth'))], admin_url('admin-post.php'));
}
function pn_svoi_mail($id, &$r) {
    if (!empty($r['mail_sent']) || !$r['email']) return true;
    $amount = pn_svoi_amount($r['cents']);
    $body = "Спасибо за поддержку podslushano.nl!\n\nВаш вклад: €$amount";
    if ($r['monthly']) $body .= " в месяц. Остановить будущие списания можно по ссылке:\n" . pn_svoi_link($id);
    $ok = wp_mail($r['email'], $r['monthly'] ? 'СВОИ — ежемесячная поддержка' : 'Спасибо за поддержку podslushano.nl', $body);
    if ($ok) { $r['mail_sent'] = true; update_option(pn_svoi_record_key($id), $r, false); }
    return $ok;
}
function pn_svoi_process($id) {
    if (!preg_match('/^tr_[A-Za-z0-9]+$/D', $id)) return true;
    // Database advisory lock prevents concurrent webhook/cron subscription creation.
    global $wpdb;
    $lock = 'pn_svoi_' . substr(hash('sha256', $wpdb->prefix . $id), 0, 48);
    if ((int)$wpdb->get_var($wpdb->prepare('SELECT GET_LOCK(%s, 0)', $lock)) !== 1) return false;
    try {
        wp_cache_delete(pn_svoi_record_key($id), 'options');
        $r = get_option(pn_svoi_record_key($id));
        if (!is_array($r)) return true; // not a first payment created by this module
        if (in_array($r['status'], ['cancelled', 'closed'], true)) return true;
        if ($r['status'] === 'active') return pn_svoi_mail($id, $r);
        $p = pn_svoi_api('GET', '/v2/payments/' . $id);
        if (is_wp_error($p)) return false;
        $status = $p['status'] ?? '';
        if (in_array($status, ['failed', 'canceled', 'expired'], true)) {
            $r['status'] = 'closed'; update_option(pn_svoi_record_key($id), $r, false); return true;
        }
        if ($status !== 'paid') return false;
        if (($p['id'] ?? '') !== $id || ($p['mode'] ?? '') !== 'live' || ($p['metadata']['source'] ?? '') !== 'svoi_wp'
            || ($p['amount']['currency'] ?? '') !== 'EUR' || pn_donation_net($p) !== $r['cents']) return false;
        if ($r['monthly']) {
            if (($p['sequenceType'] ?? '') !== 'first' || ($p['customerId'] ?? '') !== $r['customer'] || empty($r['consent_at'])) return false;
            $path = '/v2/customers/' . $r['customer'] . '/subscriptions';
            $list = pn_svoi_api('GET', $path . '?limit=250');
            if (is_wp_error($list) || !is_array($list['_embedded']['subscriptions'] ?? null) || !empty($list['_links']['next'])) return false;
            $all = $list['_embedded']['subscriptions'];
            $matches = array_values(array_filter($all, function($s) use ($id) { return ($s['metadata']['first_payment_id'] ?? '') === $id; }));
            if (count($matches) === 1) $sub = $matches[0];
            elseif (count($all) !== 0) return false;
            else {
                $start = pn_svoi_next_date($p['paidAt'] ?? '');
                if (!$start || $start < gmdate('Y-m-d')) return false; // admin reconciliation, never backcharge
                $sub = pn_svoi_api('POST', $path, ['amount' => ['currency' => 'EUR', 'value' => pn_svoi_amount($r['cents'])],
                    'interval' => '1 month', 'startDate' => $start, 'description' => 'Maandelijkse bijdrage podslushano.nl',
                    'webhookUrl' => rest_url('pn/v1/svoi/webhook'),
                    'metadata' => ['kind' => 'donation_sub', 'source' => 'svoi_wp', 'first_payment_id' => $id]], hash('sha256', 'svoi-wp:' . $id));
            }
            if (is_wp_error($sub) || !preg_match('/^sub_[A-Za-z0-9]+$/D', $sub['id'] ?? '')) return false;
            $r['subscription'] = $sub['id'];
        }
        $r['status'] = 'active'; update_option(pn_svoi_record_key($id), $r, false);
        // The existing accounting sync imports confirmed payments separately.
        return pn_svoi_mail($id, $r);
    } finally { $wpdb->get_var($wpdb->prepare('SELECT RELEASE_LOCK(%s)', $lock)); }
}
function pn_svoi_retry($id) {
    if (pn_svoi_process($id)) return;
    $r = get_option(pn_svoi_record_key($id));
    if (is_array($r) && time() - $r['created_at'] < 7 * DAY_IN_SECONDS)
        wp_schedule_single_event(time() + 900, 'pn_svoi_retry', [$id]);
    elseif (is_array($r)) update_option('pn_svoi_attention', $id, false);
}
add_action('pn_svoi_retry', 'pn_svoi_retry');
function pn_svoi_webhook($request) {
    $id = $request->get_param('id');
    if (!is_string($id) || !preg_match('/^tr_[A-Za-z0-9]+$/D', $id)) return new WP_REST_Response(null, 400);
    if (!get_option(pn_svoi_record_key($id))) return new WP_REST_Response(null, 200);
    return new WP_REST_Response(null, pn_svoi_process($id) ? 200 : 503);
}
function pn_svoi_cancel() {
    $id = sanitize_text_field(wp_unslash($_GET['payment'] ?? ''));
    $token = sanitize_text_field(wp_unslash($_GET['token'] ?? ''));
    $valid = preg_match('/^tr_[A-Za-z0-9]+$/D', $id) && hash_equals(hash_hmac('sha256', 'svoi-cancel:' . $id, wp_salt('auth')), $token);
    $r = $valid ? get_option(pn_svoi_record_key($id)) : null;
    nocache_headers(); header('Referrer-Policy: no-referrer');
    $msg = 'Ссылка не найдена. Напишите нам: podslushano.nl@gmail.com.';
    if (is_array($r) && !empty($r['subscription'])) {
        if ($r['status'] === 'cancelled') $msg = 'Поддержка уже отменена.';
        elseif ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['confirm'])) {
            $path = '/v2/customers/' . $r['customer'] . '/subscriptions/' . $r['subscription'];
            $res = pn_svoi_api('DELETE', $path);
            if (is_wp_error($res)) {
                $sub = pn_svoi_api('GET', $path);
                if (!is_wp_error($sub) && ($sub['status'] ?? '') === 'canceled') $res = [];
            }
            if (is_wp_error($res)) $msg = 'Не удалось подтвердить отмену. Повторите попытку или напишите нам.';
            else { $r['status'] = 'cancelled'; update_option(pn_svoi_record_key($id), $r, false); $msg = 'Будущие ежемесячные списания отменены. Спасибо за поддержку!'; }
        } else {
            $form = '<form method="post" action="' . esc_url(pn_svoi_link($id)) . '"><button name="confirm" value="1" type="submit">Отменить ежемесячную поддержку</button></form>';
            wp_die('Остановить будущие списания?' . $form, 'СВОИ', ['response' => 200]);
        }
    }
    wp_die(esc_html($msg), 'СВОИ', ['response' => 200]);
}
add_action('admin_post_nopriv_pn_svoi_cancel', 'pn_svoi_cancel');
add_action('admin_post_pn_svoi_cancel', 'pn_svoi_cancel');
add_action('rest_api_init', function() {
    register_rest_route('pn/v1', '/svoi/checkout', ['methods' => 'POST', 'permission_callback' => '__return_true', 'callback' => 'pn_svoi_checkout']);
    register_rest_route('pn/v1', '/svoi/webhook', ['methods' => 'POST', 'permission_callback' => '__return_true', 'callback' => 'pn_svoi_webhook']);
});
add_action('wp_head', function() {
    echo '<script id="pn-svoi-config" data-category="functional">window.PN_SUPPORT_CHECKOUT_URL=' . wp_json_encode(rest_url('pn/v1/svoi/checkout')) . ';</script>' . "\n";
});
add_action('admin_notices', function() {
    if (current_user_can('manage_options') && get_option('pn_svoi_attention'))
        echo '<div class="notice notice-warning"><p>СВОИ: платёж требует ручной сверки в Mollie: ' . esc_html(get_option('pn_svoi_attention')) . '.</p></div>';
});
