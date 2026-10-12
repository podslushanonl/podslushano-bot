<?php
/** Newsletter, allowalks notify and contact form: stored in WordPress, visible in Tools → podslushano. */
if (!defined('ABSPATH')) exit;

function pn_same_site() {
    $src = $_SERVER['HTTP_ORIGIN'] ?? ($_SERVER['HTTP_REFERER'] ?? '');
    $host = strtolower((string) wp_parse_url($src, PHP_URL_HOST));
    $home = strtolower((string) wp_parse_url(home_url(), PHP_URL_HOST));
    return $host !== '' && preg_replace('/^www\./', '', $host) === preg_replace('/^www\./', '', $home);
}

function pn_form_handler() {
    // Same-site check instead of a nonce: Cache Enabler serves cached pages whose nonce has expired.
    if (!pn_same_site()) wp_send_json_error(['msg' => 'Обновите страницу и попробуйте ещё раз.'], 403);
    $kind = sanitize_key($_POST['kind'] ?? '');
    if (!in_array($kind, ['week', 'allowalks', 'contact'], true)) wp_send_json_error(['msg' => 'Неизвестная форма.'], 400);
    $ip = $_SERVER['REMOTE_ADDR'] ?? '';
    $rl = 'pn_rl_' . md5($ip);
    $hits = (int) get_transient($rl);
    if ($hits > 8) wp_send_json_error(['msg' => 'Слишком много попыток. Попробуйте через несколько минут.'], 429);
    set_transient($rl, $hits + 1, 10 * MINUTE_IN_SECONDS);

    if ($kind === 'contact') {
        $email = sanitize_email($_POST['ce'] ?? '');
        $msg = sanitize_textarea_field($_POST['cm'] ?? '');
        if (!is_email($email) || mb_strlen($msg) < 2) wp_send_json_error(['msg' => 'Проверьте почту и текст сообщения.'], 400);
        $fields = [];
        foreach ($_POST as $k => $v) {
            if (in_array($k, ['action', 'kind'], true)) continue;
            $fields[sanitize_key($k)] = sanitize_textarea_field(wp_unslash($v));
        }
        $body = "Сообщение с сайта podslushano.nl\n\n";
        foreach ($fields as $k => $v) $body .= "$k: $v\n";
        wp_mail(get_option('admin_email'), 'podslushano.nl: сообщение с сайта', $body, ['Reply-To: ' . $email]);
        pn_store('contact', $email, $msg);
        wp_send_json_success();
    }
    $email = sanitize_email($_POST['email'] ?? '');
    if (!is_email($email)) wp_send_json_error(['msg' => 'Проверьте почту.'], 400);
    pn_store($kind, $email, '');
    wp_send_json_success();
}
add_action('wp_ajax_pn_form', 'pn_form_handler');
add_action('wp_ajax_nopriv_pn_form', 'pn_form_handler');

function pn_store($kind, $email, $msg) {
    $list = get_option('pn_forms', []);
    if (!is_array($list)) $list = [];
    if ($kind !== 'contact') {
        foreach ($list as $row) if ($row['kind'] === $kind && strcasecmp($row['email'], $email) === 0) return;
    }
    $list[] = ['kind' => $kind, 'email' => $email, 'msg' => $msg, 'at' => current_time('mysql')];
    update_option('pn_forms', array_slice($list, -5000), false);
}

add_action('admin_menu', function () {
    add_management_page('podslushano: заявки', 'podslushano: заявки', 'manage_options', 'pn-forms', function () {
        $list = array_reverse(get_option('pn_forms', []) ?: []);
        $names = ['week' => 'Неделя в Нидерландах', 'allowalks' => 'allowalks: новые прогулки', 'contact' => 'Сообщения'];
        echo '<div class="wrap"><h1>Заявки с сайта</h1><p><a class="button" href="' . esc_url(wp_nonce_url(admin_url('tools.php?page=pn-forms&csv=1'), 'pn_csv')) . '">Скачать CSV</a></p>';
        echo '<table class="widefat striped"><thead><tr><th>Дата</th><th>Форма</th><th>Почта</th><th>Сообщение</th></tr></thead><tbody>';
        foreach ($list as $r) {
            echo '<tr><td>' . esc_html($r['at']) . '</td><td>' . esc_html($names[$r['kind']] ?? $r['kind']) . '</td><td>' . esc_html($r['email']) . '</td><td>' . esc_html($r['msg']) . '</td></tr>';
        }
        if (!$list) echo '<tr><td colspan="4">Пока пусто.</td></tr>';
        echo '</tbody></table></div>';
    });
});
add_action('admin_init', function () {
    if (($_GET['page'] ?? '') !== 'pn-forms' || empty($_GET['csv']) || !current_user_can('manage_options')) return;
    check_admin_referer('pn_csv');
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename=podslushano-forms.csv');
    $out = fopen('php://output', 'w');
    fputcsv($out, ['date', 'form', 'email', 'message']);
    foreach (get_option('pn_forms', []) ?: [] as $r) fputcsv($out, [$r['at'], $r['kind'], $r['email'], $r['msg']]);
    exit;
});
