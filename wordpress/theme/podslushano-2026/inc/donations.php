<?php
/** Community support campaign. Does not create payments or change the bot. */
if (!defined('ABSPATH')) exit;

const PN_DONATION_GOAL = 50000; // Integer euro cents; one campaign, no automatic resets.
const PN_TIKKIE_EXPIRES = 1794323178; // 2026-11-10T15:06:18+00:00
function pn_donation_tikkie_active($now = null) {
    return ($now ?? time()) < PN_TIKKIE_EXPIRES && !get_option('pn_tikkie_expired', false);
}
function pn_donation_expire_tikkie() {
    if (time() < PN_TIKKIE_EXPIRES) return;
    update_option('pn_tikkie_expired', 1, false);
    wp_clear_scheduled_hook('pn_tikkie_expire');
    do_action('cache_enabler_clear_complete_cache');
}
add_action('pn_tikkie_expire', 'pn_donation_expire_tikkie');
add_action('init', function () {
    if (time() >= PN_TIKKIE_EXPIRES) {
        if (!get_option('pn_tikkie_expired')) pn_donation_expire_tikkie();
    } elseif (!wp_next_scheduled('pn_tikkie_expire')) {
        wp_schedule_single_event(PN_TIKKIE_EXPIRES, 'pn_tikkie_expire');
    }
});

function pn_donation_cents($value) {
    if (!is_scalar($value) || !preg_match('/^\d{1,9}(?:[.,]\d{1,2})?$/D', (string) $value)) return null;
    $parts = explode('.', str_replace(',', '.', (string) $value));
    return (int) $parts[0] * 100 + (int) str_pad($parts[1] ?? '', 2, '0');
}

function pn_donation_net($payment) {
    if (($payment['mode'] ?? '') !== 'live' || ($payment['status'] ?? '') !== 'paid' || ($payment['amount']['currency'] ?? '') !== 'EUR') return 0;
    $amount = pn_donation_cents($payment['amount']['value'] ?? '');
    if ($amount === null) return 0;
    foreach (['amountRefunded', 'amountChargedBack'] as $field) {
        if (!isset($payment[$field])) continue;
        if (($payment[$field]['currency'] ?? '') !== 'EUR') return 0;
        $deduction = pn_donation_cents($payment[$field]['value'] ?? '');
        if ($deduction === null) return 0;
        $amount -= $deduction;
    }
    return max(0, $amount);
}

function pn_donation_matches($payment) {
    // Only the existing donation return marker on this site's home page. Never import sales.
    $url = wp_parse_url($payment['redirectUrl'] ?? '');
    $home = wp_parse_url(home_url('/'));
    $host = preg_replace('/^www\./i', '', $url['host'] ?? '');
    $home_host = preg_replace('/^www\./i', '', $home['host'] ?? '');
    parse_str($url['query'] ?? '', $query);
    if ($host && strcasecmp($host, $home_host) === 0 && ($url['scheme'] ?? '') === 'https'
        && rtrim($url['path'] ?? '', '/') === rtrim($home['path'] ?? '', '/') && ($query['donation'] ?? '') === 'thanks') return true;
    // Optional dedicated Mollie payment-link IDs; copy pl_... from Mollie's API/dashboard.
    $ids = preg_split('/[\s,]+/', (string) get_option('pn_donation_links', ''), -1, PREG_SPLIT_NO_EMPTY);
    return !empty($payment['paymentLinkId']) && in_array($payment['paymentLinkId'], $ids, true);
}

function pn_donation_key() {
    return defined('PN_DONATION_MOLLIE_KEY') ? PN_DONATION_MOLLIE_KEY : (string) get_option('pn_donation_key', '');
}

function pn_donation_api($path) {
    // Pagination is limited to the fixed Mollie API origin; never follow arbitrary URLs.
    if (!preg_match('#^/v2/payments(?:\?[^\r\n]*)?$#D', $path)) return new WP_Error('donation_path', 'Недопустимый адрес API.');
    $res = wp_remote_get('https://api.mollie.com' . $path, [
        'timeout' => 15, 'redirection' => 0,
        'headers' => ['Authorization' => 'Bearer ' . pn_donation_key(), 'Accept' => 'application/json'],
    ]);
    if (is_wp_error($res)) return new WP_Error('donation_network', 'Mollie не ответил. Сохранены последние подтверждённые данные.');
    if (wp_remote_retrieve_response_code($res) !== 200) return new WP_Error('donation_api', 'Не удалось обновить платежи Mollie. Проверьте ключ и доступ.');
    $data = json_decode(wp_remote_retrieve_body($res), true);
    return is_array($data) && isset($data['_embedded']['payments']) ? $data : new WP_Error('donation_json', 'Некорректный ответ Mollie.');
}

add_action('init', function () {
    register_post_type('pn_donation', [
        'labels' => ['name' => 'Поддержка сообщества', 'singular_name' => 'Вклад', 'add_new_item' => 'Добавить подтверждённый вклад', 'edit_item' => 'Редактировать вклад'],
        'public' => false, 'show_ui' => true, 'show_in_rest' => false,
        'menu_icon' => 'dashicons-heart', 'supports' => ['title'],
        'capabilities' => ['edit_posts' => 'manage_options', 'edit_others_posts' => 'manage_options', 'publish_posts' => 'manage_options', 'read_private_posts' => 'manage_options', 'delete_posts' => 'manage_options', 'delete_others_posts' => 'manage_options', 'edit_post' => 'manage_options', 'read_post' => 'manage_options', 'delete_post' => 'manage_options'],
        'map_meta_cap' => false,
    ]);
    if (!get_option('pn_donation_started')) add_option('pn_donation_started', gmdate('Y-m-d\TH:i:s\Z'), '', false);
    if (!wp_next_scheduled('pn_donation_sync')) wp_schedule_event(time() + 60, 'pn_donation_five_minutes', 'pn_donation_sync');
});
add_filter('cron_schedules', function ($s) { $s['pn_donation_five_minutes'] = ['interval' => 300, 'display' => 'Каждые пять минут']; return $s; });
add_action('switch_theme', function () { wp_clear_scheduled_hook('pn_donation_sync'); });

function pn_donation_upsert($p) {
    $payment_id = $p['id'] ?? '';
    if (!preg_match('/^tr_[A-Za-z0-9]+$/D', $payment_id)) return;
    $posts = get_posts(['post_type' => 'pn_donation', 'post_status' => 'any', 'meta_key' => '_pn_payment', 'meta_value' => $payment_id, 'numberposts' => 1]);
    $net = pn_donation_net($p);
    if (!$posts && !$net) return;
    $id = $posts ? $posts[0]->ID : wp_insert_post(['post_type' => 'pn_donation', 'post_status' => 'publish', 'post_title' => 'Анонимный участник'], true);
    if (is_wp_error($id) || !$id) return;
    update_post_meta($id, '_pn_payment', $payment_id);
    update_post_meta($id, '_pn_cents', $net);
    update_post_meta($id, '_pn_confirmed', 1);
    update_post_meta($id, '_pn_received', $p['paidAt'] ?? $p['createdAt'] ?? '');
}

function pn_donation_sync() {
    if (!preg_match('/^live_[A-Za-z0-9]+$/D', pn_donation_key())) return;
    $lock = (int) get_option('pn_donation_lock', 0);
    if ($lock && $lock < time() - 180) {
        // Remove only the stale value, never a newer worker's lease.
        global $wpdb;
        $wpdb->query($wpdb->prepare("DELETE FROM {$wpdb->options} WHERE option_name = %s AND option_value = %s", 'pn_donation_lock', (string) $lock));
        wp_cache_delete('pn_donation_lock', 'options');
        wp_cache_delete('notoptions', 'options');
    }
    if (!add_option('pn_donation_lock', time(), '', false)) return;
    try {
        $path = get_option('pn_donation_cursor', '/v2/payments?limit=250');
        $start = strtotime(get_option('pn_donation_started'));
        // Continue a bounded full scan across cron runs, including old refunds and recurring payments.
        for ($page = 0; $page < 3; $page++) {
            $data = pn_donation_api($path);
            if (is_wp_error($data)) { update_option('pn_donation_error', $data->get_error_message(), false); return; }
            $before_start = false;
            foreach ($data['_embedded']['payments'] as $p) {
                if (strtotime($p['createdAt'] ?? '') < $start) { $before_start = true; continue; }
                if (pn_donation_matches($p)) pn_donation_upsert($p);
            }
            $next = $data['_links']['next']['href'] ?? '';
            if ($before_start || !$next) { delete_option('pn_donation_cursor'); break; }
            if (strpos($next, 'https://api.mollie.com/v2/payments?') !== 0) { update_option('pn_donation_error', 'Неожиданный адрес следующей страницы Mollie.', false); return; }
            $path = substr($next, strlen('https://api.mollie.com'));
            update_option('pn_donation_cursor', $path, false);
        }
        update_option('pn_donation_synced', gmdate('c'), false);
        delete_option('pn_donation_error');
    } finally { delete_option('pn_donation_lock'); }
}
add_action('pn_donation_sync', 'pn_donation_sync');

function pn_donation_public() {
    $sum = 0; $donors = [];
    $start = strtotime(get_option('pn_donation_started'));
    $posts = get_posts(['post_type' => 'pn_donation', 'post_status' => 'publish', 'numberposts' => -1, 'meta_key' => '_pn_received', 'orderby' => ['meta_value' => 'DESC', 'ID' => 'DESC']]);
    foreach ($posts as $p) {
        $cents = (int) get_post_meta($p->ID, '_pn_cents', true);
        $date = get_post_meta($p->ID, '_pn_received', true);
        if ($cents <= 0 || !get_post_meta($p->ID, '_pn_confirmed', true) || strtotime($date) < $start) continue;
        $sum += $cents;
        $donors[] = ['name' => get_post_meta($p->ID, '_pn_consent', true) ? wp_strip_all_tags($p->post_title) : 'Анонимный участник', 'amount_cents' => $cents];
    }
    $synced = get_option('pn_donation_synced', '');
    $stale = pn_donation_key() && (!$synced || strtotime($synced) < time() - 900);
    return ['tikkie_active' => pn_donation_tikkie_active(), 'goal_cents' => PN_DONATION_GOAL, 'raised_cents' => $sum, 'remaining_cents' => max(0, PN_DONATION_GOAL - $sum), 'count' => count($donors), 'supporters' => array_slice($donors, 0, 20), 'updated_at' => $synced, 'delayed' => $stale || (bool) get_option('pn_donation_error', '') || (bool) get_option('pn_donation_cursor', '')];
}
add_action('rest_api_init', function () {
    register_rest_route('pn/v1', '/donations', ['methods' => 'GET', 'permission_callback' => '__return_true', 'callback' => function () {
        $res = new WP_REST_Response(pn_donation_public());
        $res->header('Cache-Control', 'no-store, max-age=0');
        return $res;
    }]);
});
add_action('wp_head', function () {
    if (is_page('links')) return;
    // Separate tag: preserve the existing window.PN data script and its Complianz fallback parser.
    echo '<script id="pn-donation-config" data-category="functional">window.PN_DONATIONS_URL=' . wp_json_encode(rest_url('pn/v1/donations')) . ';</script>' . "\n";
});

add_action('add_meta_boxes_pn_donation', function () {
    add_meta_box('pn-donation-details', 'Подтверждённый вклад', function ($post) {
        wp_nonce_field('pn_donation_save', 'pn_donation_nonce');
        $payment = get_post_meta($post->ID, '_pn_payment', true);
        $cents = (int) get_post_meta($post->ID, '_pn_cents', true);
        echo '<p>В заголовке укажите имя для благодарности. Без согласия посетители увидят «Анонимный участник».</p>';
        if ($payment) echo '<p>Mollie: <code>' . esc_html($payment) . '</code>. Сумма и дата обновляются автоматически.</p>';
        echo '<p><label>Сумма, € <input name="pn_amount" type="number" min="0.01" step="0.01" value="' . esc_attr(number_format($cents / 100, 2, '.', '')) . '" ' . ($payment ? 'readonly' : '') . ' required></label></p>';
        $date = get_post_meta($post->ID, '_pn_received', true) ?: gmdate('c');
        echo '<p><label>Дата получения (UTC) <input name="pn_received" type="datetime-local" value="' . esc_attr(gmdate('Y-m-d\TH:i', strtotime($date))) . '" ' . ($payment ? 'readonly' : '') . ' required></label></p>';
        echo '<p><label><input type="checkbox" name="pn_confirmed" value="1" ' . checked(get_post_meta($post->ID, '_pn_confirmed', true), 1, false) . ($payment ? ' disabled' : '') . '> Деньги действительно получены</label></p>';
        echo '<p><label><input type="checkbox" name="pn_consent" value="1" ' . checked(get_post_meta($post->ID, '_pn_consent', true), 1, false) . '> Получено согласие опубликовать имя и сумму</label></p>';
        echo '<p>Для исправления или возврата ручного вклада снимите подтверждение. Не добавляйте вручную платежи, уже импортированные из Mollie.</p>';
    }, 'pn_donation', 'normal', 'high');
});
add_action('save_post_pn_donation', function ($id) {
    if (!current_user_can('manage_options') || wp_is_post_revision($id) || (defined('DOING_AUTOSAVE') && DOING_AUTOSAVE)
        || !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['pn_donation_nonce'] ?? '')), 'pn_donation_save')) return;
    update_post_meta($id, '_pn_consent', isset($_POST['pn_consent']) ? 1 : 0);
    if (!get_post_meta($id, '_pn_payment', true)) {
        $cents = pn_donation_cents(wp_unslash($_POST['pn_amount'] ?? ''));
        $raw_date = sanitize_text_field(wp_unslash($_POST['pn_received'] ?? ''));
        $date = preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/D', $raw_date) ? strtotime($raw_date . ' UTC') : false;
        if ($cents === null || $cents < 1 || !$date || $date > time() + 60) { update_post_meta($id, '_pn_confirmed', 0); return; }
        update_post_meta($id, '_pn_cents', $cents);
        update_post_meta($id, '_pn_received', gmdate('c', $date));
        update_post_meta($id, '_pn_confirmed', isset($_POST['pn_confirmed']) ? 1 : 0);
    }
});

add_action('admin_menu', function () {
    add_submenu_page('edit.php?post_type=pn_donation', 'Настройки сбора', 'Настройки сбора', 'manage_options', 'pn-donation-settings', 'pn_donation_settings');
});
function pn_donation_settings() {
    if (!current_user_can('manage_options')) return;
    $notice = '';
    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        check_admin_referer('pn_donation_settings');
        $key = trim(wp_unslash($_POST['pn_key'] ?? ''));
        if ($key && !preg_match('/^live_[A-Za-z0-9]+$/D', $key)) $notice = 'Нужен действующий live-ключ Mollie. Тестовые платежи в сбор не попадают.';
        else {
            if ($key && !defined('PN_DONATION_MOLLIE_KEY')) update_option('pn_donation_key', $key, false);
            if (isset($_POST['pn_disconnect'])) delete_option('pn_donation_key');
            $links = preg_split('/[\s,]+/', sanitize_text_field(wp_unslash($_POST['pn_links'] ?? '')), -1, PREG_SPLIT_NO_EMPTY);
            update_option('pn_donation_links', implode(' ', array_filter($links, function ($id) { return preg_match('/^pl_[A-Za-z0-9]+$/D', $id); })), false);
            $raw_date = sanitize_text_field(wp_unslash($_POST['pn_start'] ?? ''));
            $date = preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/D', $raw_date) ? strtotime($raw_date . ' UTC') : false;
            if ($date && $date <= time()) update_option('pn_donation_started', gmdate('c', $date), false);
            delete_option('pn_donation_cursor');
            if (!isset($_POST['pn_disconnect'])) pn_donation_sync();
            $notice = 'Настройки сохранены.';
        }
    }
    echo '<div class="wrap"><h1>Поддержка Podslushano.nl · цель €500</h1>';
    if ($notice) echo '<div class="notice notice-info"><p>' . esc_html($notice) . '</p></div>';
    echo '<p>Это один сбор без ежемесячного обнуления. Шкала считает только подтверждённые поступления с даты начала.</p><form method="post">';
    wp_nonce_field('pn_donation_settings');
    echo '<table class="form-table"><tr><th>Начало сбора (UTC)</th><td><input type="datetime-local" name="pn_start" required value="' . esc_attr(gmdate('Y-m-d\TH:i', strtotime(get_option('pn_donation_started')))) . '"></td></tr>';
    echo '<tr><th>Live API key Mollie</th><td><input type="password" name="pn_key" autocomplete="new-password" value="" placeholder="' . (pn_donation_key() ? 'Ключ подключён' : 'live_…') . '" ' . (defined('PN_DONATION_MOLLIE_KEY') ? 'disabled' : '') . '><p class="description">Тот же профиль Mollie, который принимает донаты. Ключ хранится только на сервере; пустое поле сохраняет текущий ключ. Можно задать PN_DONATION_MOLLIE_KEY в wp-config.php.</p><label><input type="checkbox" name="pn_disconnect"> Отключить сохранённый ключ</label></td></tr>';
    echo '<tr><th>Отдельные платёжные ссылки</th><td><input class="regular-text" name="pn_links" value="' . esc_attr(get_option('pn_donation_links', '')) . '" placeholder="pl_…"><p class="description">Необязательно: API ID ссылок Mollie, используемых исключительно для донатов. Ссылки продаж сюда не добавляйте.</p></td></tr></table>';
    submit_button('Сохранить и обновить');
    echo '</form><p>Автоимпорт: только live-платежи EUR с возвратом на главную этого сайта с ?donation=thanks или из указанных ссылок. Другие платежи не учитываются. Возвраты и оспоренные суммы вычитаются. Обновление через WP-Cron примерно раз в пять минут при посещениях сайта.</p>';
    echo '<p>Регулярные списания без адреса возврата или ID платёжной ссылки не импортируются: их можно добавить как подтверждённые вклады вручную. Имена из банковских реквизитов не публикуются. Для имени получите согласие и отредактируйте соответствующий вклад.</p>';
    echo '<p>Последнее обновление: ' . esc_html(get_option('pn_donation_synced', '') ?: 'ещё не выполнялось') . '</p>';
    if ($err = get_option('pn_donation_error')) echo '<p><strong>' . esc_html($err) . '</strong></p>';
    echo '</div>';
}
