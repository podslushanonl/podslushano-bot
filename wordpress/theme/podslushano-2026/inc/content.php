<?php
/**
 * Афиша, вакансии и партнёры в админке WordPress.
 * Three private post types (the app renders them): pn_event, pn_job, pn_partner.
 * Every field of the old JSON items is a meta field (_pn_<name>) in one meta box.
 * The data for the app is built in inc/data.php (pn_events, pn_jobs, pn_partners).
 */
if (!defined('ABSPATH')) exit;

const PN_CONTENT_TYPES = ['pn_event', 'pn_job', 'pn_partner'];

/* ---------- fields: name => [label, kind, hint] ---------- */
function pn_content_fields($type) {
    $f = [
        'pn_event' => [
            's' => ['Подзаголовок', 'text', 'Одна строка под названием, например «Встреча с автором бестселлера «Сказка»».'],
            'date' => ['Дата', 'date', 'Обязательно. После этой даты событие исчезает с сайта.'],
            'end' => ['Дата окончания', 'date', 'Только для фестивалей и выставок на несколько дней.'],
            'time' => ['Начало', 'time', ''],
            'doors' => ['Открытие дверей', 'time', ''],
            'venue' => ['Площадка', 'text', 'Например, Zuiderkerk. Названия пишем по-голландски, латиницей.'],
            'addr' => ['Адрес', 'text', 'Например, Zuiderkerkhof 72, 1011 WB Amsterdam.'],
            'city' => ['Город', 'text', 'Латиницей: Amsterdam, Den Haag, Tilburg.'],
            'price' => ['Цена', 'text', 'Например, «от €30». Цена со словом «от» видна на карточке.'],
            'org' => ['Организатор', 'text', ''],
            'age' => ['Возраст', 'text', 'Например, 18+. Можно оставить пустым.'],
            'lang' => ['Язык', 'text', 'Например, «русский» или «русский, украинский».'],
            'cat' => ['Категория', 'cat', 'Фильтр на странице афиши.'],
            'url' => ['Ссылка на билеты', 'url', ''],
            'tickets' => ['Варианты билетов', 'tickets', 'Одна строка — один вариант: название | цена | пометка. Пример: VIP | €130,90 | распродано. Можно оставить пустым.'],
            'note' => ['Примечание', 'textarea', 'Мелкий текст под описанием, например условия возврата билетов.'],
            'partner' => ['Партнёр', 'check', 'Метка «Партнёр» на карточке и на странице события.'],
            'links' => ['Показывать на /links/', 'check', 'Событие попадёт в ленту афиши на странице /links/ для Instagram.'],
            'pos' => ['Фокус постера', 'pos', 'Где главное на картинке, если её обрезают: например «30% center» или «72% 30%». Пусто — по центру.'],
        ],
        'pn_job' => [
            'company' => ['Компания', 'text', ''],
            'city' => ['Город', 'text', 'Латиницей, например Haarlem, или «удалённо, Нидерланды».'],
            'lang' => ['Язык', 'text', 'Например, «русский» или «русский, украинский». По этому полю работает фильтр.'],
            'type' => ['Занятость', 'text', 'Например, «полная занятость».'],
            'salary' => ['Зарплата', 'text', 'Можно оставить пустым.'],
            'posted' => ['Дата публикации', 'date', 'Когда вакансия опубликована у работодателя.'],
            'source' => ['Источник', 'text', 'Например, LinkedIn или Jobbird.'],
            'url' => ['Ссылка на вакансию', 'url', 'Куда ведёт кнопка «Откликнуться».'],
            'until' => ['Показывать до', 'date', 'Необязательно. После этой даты вакансия скрывается.'],
        ],
        'pn_partner' => [
            'name' => ['Название партнёра', 'text', 'Видно над заголовком, например NUMR или Somewhere.show.'],
            'text' => ['Текст', 'textarea', 'Одно-два предложения.'],
            'cta' => ['Текст кнопки', 'text', 'Например, «Купить билеты».'],
            'url' => ['Ссылка', 'url', 'Метки utm добавляются автоматически, если своих в ссылке нет.'],
            'until' => ['Показывать до', 'date', 'После этой даты блок исчезает со страницы /links/.'],
            'pos' => ['Фокус картинки', 'pos', 'Например «30% center». Пусто — по центру.'],
        ],
    ];
    return $f[$type] ?? [];
}

function pn_content_cats() {
    return ['концерт', 'стендап', 'театр', 'фестиваль', 'выставка', 'ярмарка', 'встреча', 'для детей'];
}

/* ---------- post types ---------- */
function pn_content_labels($many, $one, $acc, $new, $gen_many, $img = null) {
    $l = [
        'name' => $many, 'singular_name' => $one, 'menu_name' => $many, 'name_admin_bar' => $one,
        'add_new' => 'Добавить', 'add_new_item' => 'Добавить ' . $acc, 'new_item' => $new,
        'edit_item' => 'Изменить ' . $acc, 'view_item' => 'Посмотреть', 'all_items' => 'Все ' . $gen_many,
        'search_items' => 'Найти', 'not_found' => 'Пока ничего нет', 'not_found_in_trash' => 'В корзине пусто',
        'items_list' => $many, 'item_published' => 'Опубликовано.', 'item_updated' => 'Сохранено.',
    ];
    if ($img) {
        $l += ['featured_image' => $img[0], 'set_featured_image' => $img[1], 'remove_featured_image' => $img[2], 'use_featured_image' => $img[1]];
    }
    return $l;
}
add_action('init', function () {
    $base = ['public' => false, 'show_ui' => true, 'show_in_menu' => true, 'show_in_nav_menus' => false, 'show_in_admin_bar' => true,
        'exclude_from_search' => true, 'publicly_queryable' => false, 'has_archive' => false, 'rewrite' => false, 'query_var' => false,
        'show_in_rest' => false, 'capability_type' => 'post', 'map_meta_cap' => true];
    register_post_type('pn_event', $base + [
        'labels' => pn_content_labels('Афиша', 'Событие', 'событие', 'Новое событие', 'события', ['Постер', 'Выбрать постер', 'Убрать постер']),
        'description' => 'Концерты, стендап, фестивали: /events/, главная, поиск и /links/.',
        'menu_icon' => 'dashicons-tickets-alt', 'menu_position' => 6,
        'supports' => ['title', 'editor', 'thumbnail'],
    ]);
    register_post_type('pn_job', $base + [
        'labels' => pn_content_labels('Вакансии', 'Вакансия', 'вакансию', 'Новая вакансия', 'вакансии'),
        'description' => 'Вакансии на странице /work/.',
        'menu_icon' => 'dashicons-businessman', 'menu_position' => 7,
        'supports' => ['title', 'editor'],
    ]);
    register_post_type('pn_partner', $base + [
        'labels' => pn_content_labels('Партнёры', 'Партнёр', 'партнёра', 'Новый партнёр', 'партнёры', ['Картинка', 'Выбрать картинку', 'Убрать картинку']),
        'description' => 'Карусель партнёров на странице /links/.',
        'menu_icon' => 'dashicons-megaphone', 'menu_position' => 8,
        'supports' => ['title', 'thumbnail', 'page-attributes'],
    ]);
});

add_filter('enter_title_here', function ($t, $post) {
    $m = ['pn_event' => 'Название события, например «LOBODA»', 'pn_job' => 'Должность', 'pn_partner' => 'Заголовок предложения'];
    return $m[$post->post_type] ?? $t;
}, 10, 2);

add_action('edit_form_after_title', function ($post) {
    $m = ['pn_event' => 'Ниже — описание события: каждый абзац станет абзацем на странице события.',
        'pn_job' => 'Ниже — описание вакансии: обязанности и требования, два-три предложения.'];
    if (isset($m[$post->post_type])) echo '<p class="description" style="margin:12px 0 4px">' . esc_html($m[$post->post_type]) . '</p>';
});

/* ---------- Latin addresses: a Russian title gets a transliterated slug (/events/<slug>/ accepts only a-z, 0-9 and "-") ---------- */
function pn_translit($s) {
    $map = ['а' => 'a', 'б' => 'b', 'в' => 'v', 'г' => 'g', 'д' => 'd', 'е' => 'e', 'ё' => 'e', 'ж' => 'zh', 'з' => 'z', 'и' => 'i', 'й' => 'y',
        'к' => 'k', 'л' => 'l', 'м' => 'm', 'н' => 'n', 'о' => 'o', 'п' => 'p', 'р' => 'r', 'с' => 's', 'т' => 't', 'у' => 'u', 'ф' => 'f',
        'х' => 'kh', 'ц' => 'ts', 'ч' => 'ch', 'ш' => 'sh', 'щ' => 'shch', 'ъ' => '', 'ы' => 'y', 'ь' => '', 'э' => 'e', 'ю' => 'yu', 'я' => 'ya',
        'і' => 'i', 'ї' => 'yi', 'є' => 'ye', 'ґ' => 'g'];
    return strtr(mb_strtolower((string) $s, 'UTF-8'), $map);
}
add_filter('wp_insert_post_data', function ($data, $postarr) {
    if (!in_array($data['post_type'], PN_CONTENT_TYPES, true) || in_array($data['post_status'], ['auto-draft', 'trash'], true)) return $data;
    $slug = urldecode((string) $data['post_name']);
    if ($slug !== '' && preg_match('/^[a-z0-9-]+$/', $slug)) return $data;
    $base = sanitize_title(pn_translit($slug !== '' ? $slug : $data['post_title']));
    $base = preg_replace('/[^a-z0-9-]/', '', $base) ?: str_replace('pn_', '', $data['post_type']);
    $data['post_name'] = wp_unique_post_slug($base, (int) ($postarr['ID'] ?? 0), 'publish', $data['post_type'], 0);
    return $data;
}, 10, 2);

/* ---------- meta box ---------- */
add_action('add_meta_boxes', function () {
    $t = ['pn_event' => 'Данные события', 'pn_job' => 'Данные вакансии', 'pn_partner' => 'Данные партнёра'];
    foreach ($t as $type => $title) {
        add_meta_box('pn_fields', $title, 'pn_content_box', $type, 'normal', 'high');
    }
});

function pn_content_box($post) {
    wp_nonce_field('pn_content_save', 'pn_content_nonce');
    $fields = pn_content_fields($post->post_type);
    echo '<style>.pn-f{margin:0 0 14px}.pn-f label{display:block;font-weight:600;margin-bottom:4px}.pn-f input[type=text],.pn-f input[type=url],.pn-f input[type=date],.pn-f input[type=time],.pn-f textarea{width:100%;max-width:640px;box-sizing:border-box}.pn-f .description{margin-top:4px}.pn-f.pn-check label{font-weight:400}.pn-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:0 18px;max-width:680px}</style>';
    if ($post->post_type === 'pn_event') {
        echo '<p class="description">Постер загружается в блоке «Постер» (справа, а на телефоне выше этого блока). Адрес страницы /events/&lt;адрес&gt;/ берётся из «Ярлыка» и создаётся латиницей автоматически.</p>';
    } elseif ($post->post_type === 'pn_partner') {
        echo '<p class="description">Картинка загружается в блоке «Картинка». Порядок в карусели — поле «Порядок» в блоке атрибутов: меньшее число показывается раньше.</p>';
    }
    $short = ['date', 'end', 'time', 'doors', 'posted', 'until', 'age', 'price', 'city', 'lang', 'type', 'cat', 'source', 'company', 'cta', 'name', 'pos'];
    $open = false;
    foreach ($fields as $k => [$label, $kind, $hint]) {
        $v = (string) get_post_meta($post->ID, '_pn_' . $k, true);
        $id = 'pn_' . $k;
        $is_short = in_array($k, $short, true) && $kind !== 'check';
        if ($is_short && !$open) { echo '<div class="pn-grid">'; $open = true; }
        if (!$is_short && $open) { echo '</div>'; $open = false; }
        echo '<div class="pn-f' . ($kind === 'check' ? ' pn-check' : '') . '">';
        if ($kind === 'check') {
            echo '<label><input type="checkbox" name="' . esc_attr($id) . '" value="1"' . checked($v, '1', false) . '> <b>' . esc_html($label) . '</b></label>';
        } else {
            echo '<label for="' . esc_attr($id) . '">' . esc_html($label) . '</label>';
            if ($kind === 'textarea' || $kind === 'tickets') {
                echo '<textarea id="' . esc_attr($id) . '" name="' . esc_attr($id) . '" rows="3">' . esc_textarea($v) . '</textarea>';
            } elseif ($kind === 'cat') {
                echo '<input type="text" id="' . esc_attr($id) . '" name="' . esc_attr($id) . '" value="' . esc_attr($v) . '" list="pn_cats">';
                echo '<datalist id="pn_cats">';
                foreach (pn_content_cats() as $c) echo '<option value="' . esc_attr($c) . '">';
                echo '</datalist>';
            } else {
                $type = ['date' => 'date', 'time' => 'time', 'url' => 'url'][$kind] ?? 'text';
                $ph = ['pos' => 'center', 'time' => '19:00'][$kind] ?? '';
                echo '<input type="' . $type . '" id="' . esc_attr($id) . '" name="' . esc_attr($id) . '" value="' . esc_attr($v) . '"' . ($ph ? ' placeholder="' . esc_attr($ph) . '"' : '') . ($k === 'date' && $post->post_type === 'pn_event' ? ' required' : '') . '>';
            }
        }
        if ($hint) echo '<p class="description">' . esc_html($hint) . '</p>';
        echo '</div>';
    }
    if ($open) echo '</div>';
}

function pn_content_clean($kind, $raw) {
    $raw = wp_unslash($raw);
    switch ($kind) {
        case 'date':
            $v = sanitize_text_field($raw);
            return preg_match('/^\d{4}-\d{2}-\d{2}$/', $v) ? $v : '';
        case 'time':
            $v = sanitize_text_field($raw);
            return preg_match('/^\d{1,2}:\d{2}$/', $v) ? $v : '';
        case 'url':
            return esc_url_raw(trim($raw));
        case 'check':
            return $raw ? '1' : '';
        case 'pos':
            $v = sanitize_text_field($raw);
            return preg_match('/^[a-z0-9%. -]{1,40}$/i', $v) ? $v : '';
        case 'textarea':
        case 'tickets':
            return sanitize_textarea_field($raw);
        default:
            return sanitize_text_field($raw);
    }
}

add_action('save_post', function ($post_id, $post) {
    if (!in_array($post->post_type, PN_CONTENT_TYPES, true)) return;
    if (defined('DOING_AUTOSAVE') && DOING_AUTOSAVE) return;
    if (wp_is_post_revision($post_id)) return;
    if (!isset($_POST['pn_content_nonce']) || !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['pn_content_nonce'])), 'pn_content_save')) return;
    if (!current_user_can('edit_post', $post_id)) return;
    foreach (pn_content_fields($post->post_type) as $k => [$label, $kind]) {
        $v = pn_content_clean($kind, $_POST['pn_' . $k] ?? '');
        update_post_meta($post_id, '_pn_' . $k, $v);
    }
    if ($post->post_type === 'pn_event' && $post->post_status === 'publish' && !get_post_meta($post_id, '_pn_date', true)) {
        set_transient('pn_notice_' . get_current_user_id(), 'Укажите дату события: без даты оно не показывается на сайте.', 60);
    }
}, 10, 2);

add_action('admin_notices', function () {
    $k = 'pn_notice_' . get_current_user_id();
    if ($m = get_transient($k)) {
        delete_transient($k);
        echo '<div class="notice notice-warning"><p>' . esc_html($m) . '</p></div>';
    }
});

// Edited content must show at once: clear Cache Enabler (it caches /links/ and normal pages).
add_action('save_post', function ($post_id, $post) {
    if (in_array($post->post_type, PN_CONTENT_TYPES, true) && !wp_is_post_revision($post_id)) do_action('cache_enabler_clear_complete_cache');
}, 20, 2);

/* ---------- admin lists ---------- */
function pn_admin_date($d) {
    if (!$d) return '—';
    $t = strtotime($d);
    $m = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
    return intval(date('j', $t)) . ' ' . $m[intval(date('n', $t)) - 1] . ' ' . date('Y', $t);
}
function pn_admin_cols($type, $cols) {
    $out = [];
    foreach ($cols as $k => $v) {
        if ($k === 'date') continue;
        $out[$k] = $v;
        if ($k === 'title') {
            if ($type === 'pn_event') $out += ['pn_date' => 'Дата', 'pn_city' => 'Город', 'pn_links' => '/links/'];
            if ($type === 'pn_job') $out += ['pn_company' => 'Компания', 'pn_city' => 'Город', 'pn_until' => 'Показывать до'];
            if ($type === 'pn_partner') $out += ['pn_until' => 'Показывать до', 'pn_thumb' => 'Картинка'];
        }
    }
    return $out;
}
foreach (PN_CONTENT_TYPES as $pn_type) {
    add_filter("manage_{$pn_type}_posts_columns", function ($cols) use ($pn_type) { return pn_admin_cols($pn_type, $cols); });
    add_action("manage_{$pn_type}_posts_custom_column", function ($col, $id) {
        $today = pn_today();
        switch ($col) {
            case 'pn_date':
                $d = get_post_meta($id, '_pn_date', true);
                $end = get_post_meta($id, '_pn_end', true);
                $t = get_post_meta($id, '_pn_time', true);
                echo esc_html(pn_admin_date($d) . ($end && $end !== $d ? ' – ' . pn_admin_date($end) : '') . ($t ? ', ' . $t : ''));
                if ($d && ($end ?: $d) < $today) echo '<br><span style="color:#b32d2e">прошло, на сайте не видно</span>';
                break;
            case 'pn_until':
                $u = get_post_meta($id, '_pn_until', true);
                echo esc_html($u ? pn_admin_date($u) : 'без срока');
                if ($u && $u < $today) echo '<br><span style="color:#b32d2e">срок прошёл, на сайте не видно</span>';
                break;
            case 'pn_city':
                echo esc_html(get_post_meta($id, '_pn_city', true) ?: '—');
                break;
            case 'pn_company':
                echo esc_html(get_post_meta($id, '_pn_company', true) ?: '—');
                break;
            case 'pn_links':
                echo get_post_meta($id, '_pn_links', true) ? 'да' : '—';
                break;
            case 'pn_thumb':
                echo get_the_post_thumbnail($id, [80, 80]) ?: '—';
                break;
        }
    }, 10, 2);
}
add_filter('manage_edit-pn_event_sortable_columns', function ($c) { $c['pn_date'] = 'pn_date'; return $c; });
add_filter('manage_edit-pn_job_sortable_columns', function ($c) { $c['pn_until'] = 'pn_until'; return $c; });
add_filter('manage_edit-pn_partner_sortable_columns', function ($c) { $c['pn_until'] = 'pn_until'; return $c; });
// Events are listed by date (nearest first), partners by their carousel order.
add_action('pre_get_posts', function ($q) {
    if (!is_admin() || !$q->is_main_query()) return;
    $type = $q->get('post_type');
    $ob = $q->get('orderby');
    if ($type === 'pn_event' && (!$ob || $ob === 'pn_date')) {
        $q->set('meta_query', ['relation' => 'OR', 'pn_date' => ['key' => '_pn_date', 'compare' => 'EXISTS'], 'pn_nodate' => ['key' => '_pn_date', 'compare' => 'NOT EXISTS']]);
        $q->set('orderby', ['pn_date' => $q->get('order') ?: 'ASC', 'title' => 'ASC']);
    } elseif (in_array($type, ['pn_job', 'pn_partner'], true) && $ob === 'pn_until') {
        $q->set('meta_key', '_pn_until');
        $q->set('orderby', 'meta_value');
    } elseif ($type === 'pn_partner' && !$ob) {
        $q->set('orderby', ['menu_order' => 'ASC', 'date' => 'DESC']);
    }
});
