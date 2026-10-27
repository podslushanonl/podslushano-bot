<?php
/** Isolated accounting tests: php wordpress/tests/donations.php. No live payments. */
define('ABSPATH', __DIR__);
$options = ['pn_donation_started' => '2026-10-01T00:00:00Z', 'pn_donation_key' => 'live_fixture'];
$posts = []; $meta = []; $responses = []; $requests = [];
class WP_Error { private $message; function __construct($code, $message) { $this->message = $message; } function get_error_message() { return $this->message; } }
function is_wp_error($v) { return $v instanceof WP_Error; }
function add_action(...$args) {}
function add_filter(...$args) {}
function get_option($key, $default = false) { return $GLOBALS['options'][$key] ?? $default; }
function update_option($key, $value, ...$args) { $GLOBALS['options'][$key] = $value; }
function add_option($key, $value, ...$args) { if (array_key_exists($key, $GLOBALS['options'])) return false; $GLOBALS['options'][$key] = $value; return true; }
function delete_option($key) { unset($GLOBALS['options'][$key]); }
function wp_parse_url($url) { return parse_url($url); }
function home_url($path) { return 'https://www.podslushano.nl' . $path; }
function wp_strip_all_tags($s) { return strip_tags($s); }
function get_post_meta($id, $key, ...$args) { return $GLOBALS['meta'][$id][$key] ?? ''; }
function update_post_meta($id, $key, $value) { $GLOBALS['meta'][$id][$key] = $value; }
function wp_insert_post($p, ...$args) { $id = count($GLOBALS['posts']) + 1; $GLOBALS['posts'][$id] = (object) (['ID' => $id] + $p); return $id; }
function get_posts($args) {
    $list = array_values(array_filter($GLOBALS['posts'], function ($p) use ($args) {
        if ($args['post_status'] !== 'any' && $p->post_status !== $args['post_status']) return false;
        return !isset($args['meta_key'], $args['meta_value']) || get_post_meta($p->ID, $args['meta_key']) === $args['meta_value'];
    }));
    if (($args['order'] ?? '') === 'DESC') $list = array_reverse($list);
    if (is_array($args['orderby'] ?? null)) usort($list, function ($a, $b) {
        return strcmp(get_post_meta($b->ID, '_pn_received'), get_post_meta($a->ID, '_pn_received')) ?: $b->ID <=> $a->ID;
    });
    return ($args['numberposts'] ?? -1) > 0 ? array_slice($list, 0, $args['numberposts']) : $list;
}
function wp_remote_get($url, $args) { $GLOBALS['requests'][] = $url; return array_shift($GLOBALS['responses']) ?: new WP_Error('network', 'offline'); }
function wp_remote_retrieve_response_code($r) { return $r['status']; }
function wp_remote_retrieve_body($r) { return json_encode($r['body']); }
require __DIR__ . '/../theme/podslushano-2026/inc/donations.php';

$checks = 0;
function eq($got, $expected, $why) { $GLOBALS['checks']++; if ($got !== $expected) throw new Exception($why . ': ' . json_encode([$got, $expected])); }
function payment($patch = []) {
    return array_replace_recursive(['id' => 'tr_A1', 'mode' => 'live', 'status' => 'paid', 'amount' => ['currency' => 'EUR', 'value' => '50.00'], 'createdAt' => '2026-10-20T10:00:00Z', 'paidAt' => '2026-10-20T10:01:00Z', 'redirectUrl' => 'https://www.podslushano.nl/?donation=thanks'], $patch);
}
eq(pn_donation_cents('50.01'), 5001, 'integer cents');
eq(pn_donation_cents('7,5'), 750, 'decimal comma');
foreach (['-1', '1.001', 'NaN', '1e3', '', '<script>'] as $v) eq(pn_donation_cents($v), null, 'reject malformed money');
eq(pn_donation_net(payment()), 5000, 'paid donation');
foreach (['open', 'pending', 'failed', 'canceled', 'expired', 'authorized'] as $status) eq(pn_donation_net(payment(['status' => $status])), 0, 'not paid');
eq(pn_donation_net(payment(['mode' => 'test'])), 0, 'test excluded');
eq(pn_donation_net(payment(['amount' => ['currency' => 'USD']])), 0, 'non EUR excluded');
eq(pn_donation_net(payment(['amountRefunded' => ['currency' => 'EUR', 'value' => '10.25']])), 3975, 'partial refund');
eq(pn_donation_net(payment(['amountChargedBack' => ['currency' => 'EUR', 'value' => '50.00']])), 0, 'chargeback');
eq(pn_donation_net(payment(['amountRefunded' => ['currency' => 'EUR', 'value' => '80.00']])), 0, 'never negative');
eq(pn_donation_matches(payment()), true, 'donation marker');
eq(pn_donation_matches(payment(['redirectUrl' => 'https://podslushano.nl/?donation=thanks'])), true, 'canonical www alias');
foreach (['https://evil.test/?donation=thanks', 'https://www.podslushano.nl.evil.test/?donation=thanks', 'https://www.podslushano.nl/?order=thanks', 'https://www.podslushano.nl/shop/?donation=thanks', 'http://www.podslushano.nl/?donation=thanks', ''] as $url) eq(pn_donation_matches(payment(['redirectUrl' => $url])), false, 'exclude unrelated payments');
update_option('pn_donation_links', 'pl_Allowed');
eq(pn_donation_matches(payment(['redirectUrl' => '', 'paymentLinkId' => 'pl_Allowed'])), true, 'allowlisted donation link');
eq(pn_donation_matches(payment(['redirectUrl' => '', 'paymentLinkId' => 'pl_Sale'])), false, 'sales link excluded');

pn_donation_upsert(payment()); pn_donation_upsert(payment());
eq(count($posts), 1, 'repeat import deduplicated');
$snapshot = pn_donation_public();
eq($snapshot['raised_cents'], 5000, '50 collected');
eq($snapshot['remaining_cents'], 45000, '450 remains');
$posts[1]->post_title = '<b>Anna</b>';
eq(pn_donation_public()['supporters'][0]['name'], 'Анонимный участник', 'private by default');
update_post_meta(1, '_pn_consent', 1);
eq(pn_donation_public()['supporters'][0]['name'], 'Anna', 'consented public name stripped');
pn_donation_upsert(payment(['amountRefunded' => ['currency' => 'EUR', 'value' => '10.00']]));
eq(pn_donation_public()['raised_cents'], 4000, 'refund updates existing contribution');
pn_donation_upsert(payment(['id' => 'tr_A2', 'amount' => ['value' => '560.00']]));
eq(pn_donation_public()['raised_cents'], 60000, 'over goal preserves actual total');
eq(pn_donation_public()['remaining_cents'], 0, 'over goal remaining zero');
update_post_meta(2, '_pn_confirmed', 0);
eq(pn_donation_public()['count'], 1, 'unconfirmed excluded');
update_post_meta(1, '_pn_received', '2026-09-30T23:59:00Z');
eq(pn_donation_public()['raised_cents'], 0, 'before campaign excluded');

$posts = []; $meta = [];
$responses[] = ['status' => 200, 'body' => ['_embedded' => ['payments' => [payment(), payment(['id' => 'tr_Sale', 'redirectUrl' => 'https://www.podslushano.nl/?order=thanks'])]], '_links' => ['next' => null]]];
pn_donation_sync();
eq(count($posts), 1, 'sync imports only donations');
eq(pn_donation_public()['raised_cents'], 5000, 'sync total');
eq(get_option('pn_donation_lock'), false, 'sync releases lock');
$responses[] = new WP_Error('offline', 'offline');
pn_donation_sync();
eq(pn_donation_public()['raised_cents'], 5000, 'outage preserves confirmed total');
eq(pn_donation_public()['delayed'], true, 'outage marked stale');
eq(get_option('pn_donation_lock'), false, 'failed sync releases lock');
eq(is_wp_error(pn_donation_api('/v2/payments/../../other')), true, 'reject arbitrary API paths');
echo "Passed $checks donation accounting checks.\n";
