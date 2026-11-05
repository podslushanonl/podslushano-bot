<?php
/** SEO: города по-русски, рубрики, виджет скорости: php wordpress/tests/seo.php */
define('ABSPATH', __DIR__);
define('WP_CONTENT_DIR', sys_get_temp_dir() . '/pn-seo-test-' . getmypid());
function add_action(...$a) {}
function add_filter(...$a) {}
function wp_is_writable($p) { return is_writable($p); }
require dirname(__DIR__) . '/theme/podslushano-2026/inc/seo.php';
require dirname(__DIR__) . '/theme/podslushano-2026/inc/cities.php';
require dirname(__DIR__) . '/theme/podslushano-2026/inc/health.php';

$fail = 0;
function check($ok, $what) { global $fail; echo ($ok ? 'ok   ' : 'FAIL ') . $what . "\n"; if (!$ok) $fail++; }

// Города: у каждого латинское название, провинция и три русские формы
$cities = pn_cities();
check(count($cities) === 20, '20 городов');
foreach ($cities as $slug => $c) {
    check(count($c) === 5 && !preg_match('/[a-z]/i', $c[2] . $c[3] . $c[4]) && preg_match('/^[A-Z]/', $c[0]), "$slug: Latin + 3 русские формы");
}
$a = pn_city('amsterdam');
check(pn_city_title($a) === 'Русскоязычные в Амстердаме (Amsterdam)', 'заголовок Амстердама');
check(strpos(pn_city_desc($a), 'Русские и русскоговорящие в Амстердаме') === 0, 'описание с «русские и русскоговорящие»');
check(strpos(pn_city_desc($a), 'новости Амстердама на русском') !== false, 'родительный падеж в описании');
check(pn_city_title(pn_city('den-haag')) === 'Русскоязычные в Гааге (Den Haag)', 'Гаага в предложном падеже');
check(pn_city('nope') === null, 'неизвестный город');

// Рубрики
$t = function ($name, $slug, $tax = 'category') { return (object) ['name' => $name, 'slug' => $slug, 'taxonomy' => $tax]; };
$news = pn_rubric_seo($t('новости', 'dutch-news'));
check($news && strpos($news[0], 'Новости Нидерландов на русском') === 0, 'рубрика «новости» (строчными) узнаётся');
check(pn_rubric_seo($t('Новости', 'novosti')) === $news, 'и «Новости» с заглавной');
$sp = pn_rubric_seo($t('Справочник', '%d1%81'));
check($sp && strpos($sp[0], 'BSN, DigiD') !== false && mb_strlen($sp[1]) <= 200, 'Справочник: заголовок и описание до 200 знаков');
check(mb_strlen($news[1]) <= 200, 'Новости: описание до 200 знаков');
check(pn_rubric_seo($t('Транспорт', 'tr')) === null, 'прочие рубрики — настройки Yoast');
check(pn_rubric_seo($t('новости', 'x', 'post_tag')) === null, 'метки не трогаем');
check(pn_rubric_seo(null) === null, 'пустой термин');

// Виджет скорости: без кэша — подсказки, с кэшем Cache Enabler — галочки
@mkdir(WP_CONTENT_DIR);
$rows = pn_speed_checks();
check(count($rows) === 5, '5 проверок');
$by = []; foreach ($rows as [$name, $ok, $fix]) $by[$name] = [$ok, $fix];
check($by['Файл wp-content/advanced-cache.php от Cache Enabler'][0] === false
    && strpos($by['Файл wp-content/advanced-cache.php от Cache Enabler'][1], 'Файла нет') === 0, 'нет advanced-cache.php → подсказка');
check($by['WP_CACHE включён в wp-config.php'][0] === false, 'WP_CACHE не задан → ❌');
file_put_contents(WP_CONTENT_DIR . '/advanced-cache.php', "<?php\n// other cache plugin\n");
$rows = pn_speed_checks(); $by = []; foreach ($rows as [$name, $ok, $fix]) $by[$name] = [$ok, $fix];
check(strpos($by['Файл wp-content/advanced-cache.php от Cache Enabler'][1], 'другому плагину') !== false, 'чужой advanced-cache.php распознан');
file_put_contents(WP_CONTENT_DIR . '/advanced-cache.php', "<?php\n\$cache_enabler_dir = '/x/wp-content/plugins/cache-enabler';\n");
@mkdir(WP_CONTENT_DIR . '/cache');
$rows = pn_speed_checks(); $by = []; foreach ($rows as [$name, $ok, $fix]) $by[$name] = [$ok, $fix];
check($by['Файл wp-content/advanced-cache.php от Cache Enabler'][0] === true, 'advanced-cache.php от Cache Enabler → ✅');
check($by['Папка wp-content/cache доступна для записи'][0] === true, 'папка кэша → ✅');
@unlink(WP_CONTENT_DIR . '/advanced-cache.php'); @rmdir(WP_CONTENT_DIR . '/cache'); @rmdir(WP_CONTENT_DIR);

exit($fail ? 1 : 0);
