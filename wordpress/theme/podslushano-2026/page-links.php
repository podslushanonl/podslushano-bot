<?php
/** /links/: standalone ecosystem page for the Instagram bio link. Partners and events: data/links.json. */
if (!defined('ABSPATH')) exit;
$data = json_decode((string) @file_get_contents(PN_DIR . '/data/links.json'), true) ?: ['partners' => [], 'events' => []];
$news = array_map(function ($n) {
    return ['id' => $n['id'], 'link' => $n['link'], 'h' => $n['h'], 'cat' => $n['cat'], 'date' => $n['date'],
        'thumb' => $n['thumb'] ?: ($n['img'] ?: PN_URI . '/assets/img/group.jpg')];
}, array_slice(pn_posts('news', 3), 0, 3));
if (!$news) $news = json_decode((string) @file_get_contents(PN_DIR . '/data/links-news.json'), true) ?: [];
$html = (string) @file_get_contents(PN_DIR . '/links.html');
$json = wp_json_encode(['partners' => $data['partners'], 'events' => $data['events'], 'news' => $news]);
echo str_replace('/*PNL*/', 'window.PNL=' . $json . ';', $html);
