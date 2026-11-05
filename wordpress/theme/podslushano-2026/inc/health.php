<?php
/** Админка → Консоль: виджет «Скорость сайта» — что тормозит сайт и что нажать. Видят только админы. */
if (!defined('ABSPATH')) exit;

/* [название, в порядке ли, что сделать] */
function pn_speed_checks() {
    $op = function_exists('opcache_get_status') ? @opcache_get_status(false) : false;
    $drop_file = WP_CONTENT_DIR . '/advanced-cache.php';
    $drop = is_readable($drop_file) ? (string) @file_get_contents($drop_file, false, null, 0, 4000) : '';
    $dir = WP_CONTENT_DIR . '/cache';
    return [
        ['OPcache — кэш PHP', is_array($op) && !empty($op['opcache_enabled']),
            'Vimexx → DirectAdmin → «Select PHP version» → вкладка «Extensions» → отметить «opcache» → Save. '
            . 'Каждая страница станет быстрее в 2–3 раза.'],
        ['Плагин Cache Enabler включён', class_exists('Cache_Enabler'),
            'Плагины → Cache Enabler → «Активировать».'],
        ['WP_CACHE включён в wp-config.php', defined('WP_CACHE') && WP_CACHE,
            'Плагины → Cache Enabler → «Деактивировать», затем «Активировать». Если не помогло: Vimexx → Файловый менеджер → '
            . 'wp-config.php → над строкой «That\'s all, stop editing» добавить строку define(\'WP_CACHE\', true);'],
        ['Файл wp-content/advanced-cache.php от Cache Enabler', $drop !== '' && preg_match('/cache[ _-]enabler/i', $drop),
            $drop === '' ? 'Файла нет. Плагины → Cache Enabler → «Деактивировать», затем «Активировать» — плагин создаст его.'
                : 'Файл принадлежит другому плагину кэша. Оставьте один плагин кэша, затем Cache Enabler → «Деактивировать» → «Активировать».'],
        ['Папка wp-content/cache доступна для записи', is_dir($dir) && wp_is_writable($dir),
            'Vimexx → Файловый менеджер → wp-content → папка cache (создать, если нет) → права 755.'],
    ];
}

add_action('wp_dashboard_setup', function () {
    if (!current_user_can('manage_options')) return;
    wp_add_dashboard_widget('pn_speed', 'Скорость сайта (podslushano)', function () {
        $bad = 0;
        echo '<ul>';
        foreach (pn_speed_checks() as [$name, $ok, $fix]) {
            if (!$ok) $bad++;
            echo '<li style="margin-bottom:10px">' . ($ok ? '✅ ' : '❌ ') . '<b>' . esc_html($name) . '</b>'
                . ($ok ? '' : '<br><span style="color:#50575e">' . esc_html($fix) . '</span>') . '</li>';
        }
        echo '</ul><p>' . ($bad
            ? 'Исправьте пункты с ❌: быстрый сайт Google обходит чаще и индексирует больше страниц.'
            : 'Всё в порядке: кэш работает.') . '</p>';
    });
});
