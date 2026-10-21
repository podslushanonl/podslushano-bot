<?php
/** All front-end views render the same app shell; PHP passes the route and live data. */
if (!defined('ABSPATH')) exit;
$pn = ['route' => 'home', 'bot' => PN_BOT, 'ajax' => admin_url('admin-ajax.php'), 'cmp' => pn_complianz()];
$r = get_query_var('pn_route');
if ($r) {
    $pn['route'] = $r;
    if ($r === 'event') {
        $pn['param'] = sanitize_key(get_query_var('pn_key'));
        if (!pn_event($pn['param'])) status_header(404);
    }
} elseif (is_singular('post')) {
    $pn['route'] = 'art';
    $pn['post'] = pn_post_item(get_queried_object(), true);
} elseif (is_page() || (is_singular() && !is_attachment())) {
    $p = get_queried_object();
    $pn['route'] = 'wp';
    $pn['page'] = ['title' => html_entity_decode(get_the_title($p), ENT_QUOTES, 'UTF-8'), 'html' => apply_filters('the_content', $p->post_content)];
} elseif (is_category() || is_tag() || is_search() || is_archive()) {
    $pn['route'] = 'news';
} elseif (is_404()) {
    $pn['route'] = 'wp';
    $pn['page'] = ['title' => 'Страница не найдена', 'html' => '<p>Такой страницы нет. Попробуйте поиск или вернитесь на главную.</p>'];
}
// App pages carry live weather and specialists: keep them out of Cache Enabler. Posts and pages stay cached.
if (!in_array($pn['route'], ['art', 'wp'], true) && !defined('DONOTCACHEPAGE')) define('DONOTCACHEPAGE', true);
$pn['wx'] = pn_weather();
$pn['spec'] = pn_specialists();
$pn['posts'] = pn_posts('news');
$pn['arts'] = pn_posts('arts');
// Афиша and Вакансии from wp-admin (theme JSON while empty), upcoming only
$pn['events'] = pn_events();
$pn['jobs'] = pn_jobs();
add_action('wp_enqueue_scripts', function () use ($pn) {
    wp_add_inline_script('pn-app', 'window.PN=' . wp_json_encode($pn) . ';', 'before');
}, 30);
?><!doctype html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="<?php bloginfo('charset'); ?>">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
<?php
// Search engines get the current section with its text and real links (inc/seo.php)
ob_start();
include PN_DIR . '/shell.php';
echo pn_seo_shell(ob_get_clean(), $pn);
?>
<?php wp_footer(); ?>
</body>
</html>
