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
