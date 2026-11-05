<?php
/** Old addresses from the Search Console 404 report lead to a section: php wordpress/tests/redirects.php */
define('ABSPATH', __DIR__);
function add_action(...$a) {}
require dirname(__DIR__) . '/theme/podslushano-2026/inc/redirects.php';

$fail = 0;
function check($ok, $what) { global $fail; echo ($ok ? 'ok   ' : 'FAIL ') . $what . "\n"; if (!$ok) $fail++; }

// Search Console → «Не найдено (404)», выгрузка 04.11.2026
$old = [
    '/province-directory-noord-holland/' => '/provinces/',
    '/blog/category/posts/pnl-history/' => '/news/',
    '/anwb-roadsidea-ssistance-netherlands/' => 'spravochnik',
    '/transport-netherlands/' => '/trains/',
    '/true-stories-about-life-netherlands/' => '/news/',
    '/province-directory-zeeland/' => '/provinces/',
    '/blog/2026/01/05/stollen/' => '/news/',
    '/impressive-places-netherlands/' => '/allowalks/',
    '/blog/2026/01/12/live-content-3/' => '/live/',
    '/netherlands-hotspot/' => '/allowalks/',
    '/government-tour/' => '/allowalks/',
    '/buy-rent-car-netherlands/' => 'spravochnik',
    '/free-dutch-language-practice/' => 'spravochnik',
    '/blog/tag/%D0%B8%D0%BD%D1%82%D0%B5%D1%80%D0%B5%D1%81%D0%BD%D0%BE/' => '/news/',
    '/province-noord-brabant/' => '/provinces/',
    '/car-accident-netherlands/' => 'spravochnik',
    '/blog/author/admin/page/4/' => '/news/',
    '/integration-nl/' => 'spravochnik',
    '/blog/2026/01/18/%D0%BF%D0%B5%D0%B4%D0%B0%D0%B3%D0%BE%D0%B3-%D0%BF%D0%BE-%D0%BF%D1%80%D0%BE%D0%B3%D1%80%D0%B0%D0%BC%D0%BC%D0%B8%D1%80%D0%BE%D0%B2%D0%B0%D0%BD%D0%B8%D1%8E-%D0%B8-%D1%80%D0%BE%D0%B1%D0%BE%D1%82%D0%BE/' => '/guide/',
    '/blog/2026/01/19/van-gog/' => '/news/',
    '/blog/2026/01/12/live-content/' => '/live/',
    // уже были
    '/widget/' => '/live/',
    '/collaboration-for-business-netherlands/' => '/business/',
];
check(count($old) === 23, '21 адрес из отчёта + 2 прежних');
foreach ($old as $path => $want) {
    $got = pn_old_redirect_target($path);
    check($got === $want, "$path → " . var_export($got, true));
}
check(pn_old_redirect_target('/blog/tag/интересно/') === '/news/', 'кириллица без кодирования тоже');

// Живые адреса нового сайта не трогаем
foreach (['/', '/news/', '/guide/', '/guide/tandarts-amsterdam-12/', '/provinces/', '/trains/', '/live/',
          '/city/amsterdam/', '/events/loboda/', '/kak-oformit-bolnichnyy-ziekmelding-v-niderlandakh-v-2026/',
          '/v-utrecht-s-pamyatnoy-dorozhki-v-parke-ukrali-desyatki/', '/category/novosti/', '/blogger-in-amsterdam/',
          '/provinces-history/', '/wp-admin/', ''] as $path) {
    check(pn_old_redirect_target($path) === null, "живой адрес не перенаправляется: '$path'");
}

exit($fail ? 1 : 0);
