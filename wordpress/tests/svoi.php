<?php
/** Native recurring checkout regression tests; all Mollie responses mocked. */
require __DIR__ . '/donations.php';
define('DAY_IN_SECONDS', 86400);
class WP_REST_Response {
    public $data, $status;
    function __construct($data, $status = 200) { $this->data = $data; $this->status = $status; }
}
class SvoiRequest {
    private $body;
    function __construct($b) { $this->body = $b; }
    function get_json_params() { return $this->body; }
    function get_param($k) { return $this->body[$k] ?? null; }
}
class SvoiDB {
    public $prefix = 'wp_';
    public $locked = false;
    function prepare($s, ...$args) { return $s; }
    function get_var($s) {
        if (strpos($s, 'GET_LOCK') !== false) { if ($this->locked) return 0; $this->locked = true; return 1; }
        $this->locked = false; return 1;
    }
}
$wpdb = new SvoiDB();
$transients = []; $mail = []; $scheduled = []; $native_requests = [];
function wp_json_encode($x) { return json_encode($x); }
function rest_url($x) { return home_url('/wp-json/' . $x); }
function admin_url($x) { return home_url('/wp-admin/' . $x); }
function add_query_arg($a,$u) { return $u . '?' . http_build_query($a); }
function wp_salt($x) { return 'fixture-only-' . $x; }
function get_transient($k) { return $GLOBALS['transients'][$k] ?? false; }
function set_transient($k,$v,$ttl) { $GLOBALS['transients'][$k] = $v; }
function is_email($v) { return filter_var($v,FILTER_VALIDATE_EMAIL); }
function wp_schedule_single_event($t,$hook,$args) { $GLOBALS['scheduled'][] = [$t,$hook,$args]; return true; }
function wp_cache_delete(...$args) {}
function wp_mail($to,$subject,$body) { $GLOBALS['mail'][] = [$to,$subject,$body]; return true; }
function wp_remote_request($url,$args) { $GLOBALS['native_requests'][] = [$url,$args]; return array_shift($GLOBALS['responses']) ?: new WP_Error('network','offline'); }
require __DIR__ . '/../theme/podslushano-2026/inc/svoi.php';
function response($body,$status=200) { return ['status'=>$status,'body'=>$body]; }
eq(pn_svoi_next_date('2024-01-31T12:00:00Z'), '2024-02-29', 'leap month');
eq(pn_svoi_next_date('2025-12-31T12:00:00Z'), '2026-01-31', 'year boundary');
eq(pn_svoi_next_date(''), '', 'missing paid date');
eq(pn_svoi_amount(205), '2.05', 'exact decimal');
eq(pn_svoi_checkout(new SvoiRequest(['monthly'=>true,'amount_cents'=>199,'email'=>'a@example.com','consent'=>true]))->status,400,'minimum');
eq(pn_svoi_checkout(new SvoiRequest(['monthly'=>true,'amount_cents'=>500,'email'=>'a@example.com']))->status,400,'consent mandatory');
eq(pn_svoi_checkout(new SvoiRequest(['monthly'=>true,'amount_cents'=>500,'email'=>'bad','consent'=>true]))->status,400,'email mandatory');
eq(count($native_requests),0,'invalid checkouts cannot create payment');
$responses[] = response(['id'=>'cst_A1'],201);
$responses[] = response(['id'=>'tr_Svoi1','_links'=>['checkout'=>['href'=>'https://checkout.mollie.com/pay/fixture']]],201);
$r = pn_svoi_checkout(new SvoiRequest(['monthly'=>true,'amount_cents'=>500,'email'=>'a@example.com','consent'=>true]));
eq($r->status,200,'checkout success');
eq($r->data['checkout_url'],'https://checkout.mollie.com/pay/fixture','checkout link');
$body = json_decode($native_requests[1][1]['body'],true);
eq($body['sequenceType'],'first','first payment establishes mandate');
eq($body['webhookUrl'],'https://www.podslushano.nl/wp-json/pn/v1/svoi/webhook','native webhook');
eq(get_option(pn_svoi_record_key('tr_Svoi1'))['cents'],500,'authorization persisted');
$paid = payment(['id'=>'tr_Svoi1','customerId'=>'cst_A1','sequenceType'=>'first','amount'=>['value'=>'5.00'],'paidAt'=>gmdate('c'),'metadata'=>['source'=>'svoi_wp']]);
$responses[] = response(array_replace($paid,['status'=>'open']));
eq(pn_svoi_process('tr_Svoi1'),false,'unpaid payment never creates subscription');
eq(count($mail),0,'unpaid payment never emails');
$responses[] = response($paid);
$responses[] = response(['_embedded'=>['subscriptions'=>[]],'_links'=>['next'=>null]]);
$responses[] = response(['id'=>'sub_A1'],201);
eq(pn_svoi_process('tr_Svoi1'),true,'paid creates subscription');
eq(get_option(pn_svoi_record_key('tr_Svoi1'))['subscription'],'sub_A1','subscription recorded');
eq(count($mail),1,'confirmation sent');
eq(strpos($mail[0][2], 'pn_svoi_cancel')!==false,true,'cancel link included');
$count = count($native_requests);
eq(pn_svoi_process('tr_Svoi1'),true,'duplicate webhook');
eq(count($native_requests),$count,'duplicate no API creation');
eq(count($mail),1,'duplicate no email');
eq($wpdb->locked,false,'lock released');
$responses[] = response(['id'=>'tr_Svoi2','_links'=>['checkout'=>['href'=>'https://checkout.mollie.com/pay/once']]],201);
$r = pn_svoi_checkout(new SvoiRequest(['monthly'=>false,'amount_cents'=>100,'email'=>'']));
eq($r->status,200,'oneoff still available');
$body = json_decode(end($native_requests)[1]['body'],true);
eq(isset($body['sequenceType']),false,'oneoff not recurring');
eq(pn_svoi_webhook(new SvoiRequest(['id'=>'tr_unrelated']))->status,200,'unrelated webhook ignored');
echo "Native Svoi checks passed.\n";
