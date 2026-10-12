<?php
/** One-click import of the prepared Russian news (data/news.json) as normal WordPress posts. */
if (!defined('ABSPATH')) exit;

add_action('admin_menu', function () {
    add_management_page('podslushano: импорт новостей', 'podslushano: импорт новостей', 'manage_options', 'pn-import', 'pn_import_page');
});

function pn_import_page() {
    $done = null;
    if (isset($_POST['pn_import']) && check_admin_referer('pn_import')) $done = pn_import_news();
    echo '<div class="wrap"><h1>Импорт новостей</h1>';
    echo '<p>Создаёт подготовленные новости на русском как обычные записи с рубриками, фото и подписью автора фото. Если запись с тем же адресом уже есть, обновляются её заголовок, текст и анонс.</p>';
    if ($done !== null) echo '<div class="notice notice-success"><p>Создано или обновлено записей: ' . intval($done) . '.</p></div>';
    echo '<form method="post">';
    wp_nonce_field('pn_import');
    echo '<p><button class="button button-primary" name="pn_import" value="1">Импортировать новости</button></p></form></div>';
}

function pn_import_news() {
    require_once ABSPATH . 'wp-admin/includes/image.php';
    $items = json_decode((string) @file_get_contents(PN_DIR . '/data/news.json'), true);
    if (!is_array($items)) return 0;
    $parent = term_exists('Новости', 'category') ?: wp_insert_term('Новости', 'category', ['slug' => 'novosti']);
    $parent_id = is_array($parent) ? (int) $parent['term_id'] : (int) $parent;
    $n = 0;
    foreach (array_reverse($items) as $it) {
        $cat = term_exists($it['cat'], 'category') ?: wp_insert_term($it['cat'], 'category', ['parent' => $parent_id]);
        $cat_id = is_array($cat) ? (int) $cat['term_id'] : (int) $cat;
        $html = '';
        foreach ($it['blocks'] as $b) {
            [$t, $text] = $b;
            $html .= (strpos($t, 'h') === 0)
                ? "<!-- wp:heading -->\n<h2>" . esc_html($text) . "</h2>\n<!-- /wp:heading -->\n\n"
                : "<!-- wp:paragraph -->\n<p>" . esc_html($text) . "</p>\n<!-- /wp:paragraph -->\n\n";
        }
        if (!empty($it['src_url'])) {
            $html .= "<!-- wp:paragraph -->\n<p><em>По материалам <a href=\"" . esc_url($it['src_url']) . "\" target=\"_blank\" rel=\"noopener\">" . esc_html($it['src_name'] ?? 'NOS') . "</a>. Текст подготовила редакция podslushano.nl.</em></p>\n<!-- /wp:paragraph -->";
        }
        if ($old = get_page_by_path($it['id'], OBJECT, 'post')) {
            wp_update_post(['ID' => $old->ID, 'post_title' => $it['h'], 'post_content' => $html, 'post_excerpt' => $it['lead']]);
            $n++;
            continue;
        }
        $date = $it['date'] . ' ' . ($it['time'] ?: '09:00') . ':00';
        $pid = wp_insert_post(['post_title' => $it['h'], 'post_name' => $it['id'], 'post_content' => $html, 'post_excerpt' => $it['lead'],
            'post_status' => 'publish', 'post_date' => $date, 'post_category' => [$cat_id]], true);
        if (is_wp_error($pid)) continue;
        $file = PN_DIR . '/assets/img/' . $it['img'] . '.webp';
        if (!empty($it['img']) && file_exists($file)) {
            $up = wp_upload_bits(basename($file), null, file_get_contents($file));
            if (empty($up['error'])) {
                $att = wp_insert_attachment(['post_mime_type' => 'image/webp', 'post_title' => $it['h'], 'post_excerpt' => $it['photo_credit'] ?? '', 'post_status' => 'inherit'], $up['file'], $pid);
                if (!is_wp_error($att)) {
                    wp_update_attachment_metadata($att, wp_generate_attachment_metadata($att, $up['file']));
                    set_post_thumbnail($pid, $att);
                }
            }
        }
        $n++;
    }
    return $n;
}

/* ---------- Афиша, вакансии, партнёры: one-click import of the theme JSON into wp-admin ---------- */
add_action('admin_menu', function () {
    add_management_page('podslushano: афиша, вакансии, партнёры', 'podslushano: афиша и вакансии', 'manage_options', 'pn-import-content', 'pn_import_content_page');
});

function pn_import_content_page() {
    $done = null;
    if (isset($_POST['pn_import_content']) && check_admin_referer('pn_import_content')) $done = pn_import_content();
    echo '<div class="wrap"><h1>Импорт афиши, вакансий и партнёров</h1>';
    echo '<p>Переносит события, вакансии и партнёров из файлов темы в разделы «Афиша», «Вакансии» и «Партнёры» вместе с постерами и картинками. Дальше всё меняется в этих разделах, и сайт показывает уже их.</p>';
    echo '<p>Пока в разделе нет опубликованных записей, сайт показывает данные из файлов темы. Записи, которые уже есть (с тем же адресом), не меняются, поэтому импорт можно запускать повторно.</p>';
    if ($done !== null) {
        echo '<div class="notice notice-success"><p>Создано: событий — ' . intval($done['pn_event']) . ', вакансий — ' . intval($done['pn_job']) . ', партнёров — ' . intval($done['pn_partner']) . '.</p></div>';
    }
    echo '<form method="post">';
    wp_nonce_field('pn_import_content');
    echo '<p><button class="button button-primary" name="pn_import_content" value="1">Импортировать афишу, вакансии и партнёров</button></p></form></div>';
}

function pn_import_find($type, $slug) {
    $q = get_posts(['post_type' => $type, 'name' => $slug, 'post_status' => 'any', 'posts_per_page' => 1, 'no_found_rows' => true]);
    return $q ? $q[0] : null;
}

function pn_import_thumb($pid, $img, $title) {
    if (!$img || has_post_thumbnail($pid)) return;
    $f = basename($img);
    $file = '';
    foreach ((strpos($f, '.') === false ? [$f . '.webp', $f . '.jpg', $f . '.png'] : [$f]) as $name) {
        if (file_exists(PN_DIR . '/assets/img/' . $name)) { $file = PN_DIR . '/assets/img/' . $name; break; }
    }
    if (!$file) return;
    require_once ABSPATH . 'wp-admin/includes/image.php';
    $up = wp_upload_bits(basename($file), null, file_get_contents($file));
    if (!empty($up['error'])) return;
    $mime = wp_check_filetype($up['file'])['type'] ?: 'image/webp';
    $att = wp_insert_attachment(['post_mime_type' => $mime, 'post_title' => $title, 'post_status' => 'inherit'], $up['file'], $pid);
    if (is_wp_error($att)) return;
    wp_update_attachment_metadata($att, wp_generate_attachment_metadata($att, $up['file']));
    set_post_thumbnail($pid, $att);
}

function pn_import_post($type, $slug, $title, $content, $meta, $img, $extra = []) {
    $old = pn_import_find($type, $slug);
    if ($old) {
        pn_import_thumb($old->ID, $img, $title);
        return 0;
    }
    $pid = wp_insert_post($extra + ['post_type' => $type, 'post_title' => $title, 'post_name' => $slug, 'post_content' => $content, 'post_status' => 'publish'], true);
    if (is_wp_error($pid)) return 0;
    foreach ($meta as $k => $v) update_post_meta($pid, '_pn_' . $k, is_bool($v) ? ($v ? '1' : '') : (string) $v);
    pn_import_thumb($pid, $img, $title);
    return 1;
}

function pn_import_content() {
    $n = ['pn_event' => 0, 'pn_job' => 0, 'pn_partner' => 0];
    $links = pn_theme_json('links.json');
    $lev = [];
    foreach ($links['events'] ?? [] as $x) $lev[strtok($x['url'], '?')] = $x;
    foreach (pn_theme_json('events.json') as $e) {
        if (empty($e['key'])) continue;
        $l = $lev[strtok($e['url'] ?? '', '?')] ?? null;
        $meta = ['links' => (bool) $l, 'partner' => !empty($e['partner']), 'pos' => ($e['pos'] ?? '') ?: ($l['pos'] ?? '')];
        foreach (['s', 'date', 'end', 'time', 'doors', 'venue', 'addr', 'city', 'price', 'org', 'age', 'lang', 'cat', 'url', 'note'] as $k) $meta[$k] = $e[$k] ?? '';
        $meta['tickets'] = implode("\n", array_map(function ($t) { return implode(' | ', array_filter($t, 'strlen')); }, $e['tickets'] ?? []));
        $content = implode("\n\n", array_map('esc_html', $e['p'] ?? []));
        $n['pn_event'] += pn_import_post('pn_event', $e['key'], $e['h'], $content, $meta, $e['img'] ?? '');
    }
    foreach (pn_theme_json('jobs.json') as $j) {
        if (empty($j['id'])) continue;
        $meta = [];
        foreach (['company', 'city', 'lang', 'type', 'salary', 'posted', 'source', 'url'] as $k) $meta[$k] = $j[$k] ?? '';
        $meta['until'] = '';
        $extra = !empty($j['posted']) ? ['post_date' => $j['posted'] . ' 09:00:00'] : [];
        $n['pn_job'] += pn_import_post('pn_job', $j['id'], $j['title'], esc_html($j['about'] ?? ''), $meta, '', $extra);
    }
    foreach (array_values($links['partners'] ?? []) as $i => $x) {
        if (empty($x['id'])) continue;
        $meta = [];
        foreach (['name', 'text', 'cta', 'url', 'until', 'pos'] as $k) $meta[$k] = $x[$k] ?? '';
        $n['pn_partner'] += pn_import_post('pn_partner', $x['id'], $x['title'], '', $meta, $x['img'] ?? '', ['menu_order' => $i + 1]);
    }
    do_action('cache_enabler_clear_complete_cache');
    return $n;
}
