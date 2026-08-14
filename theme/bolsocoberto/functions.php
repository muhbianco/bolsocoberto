<?php
/**
 * Bolso Coberto — tema filho do Twenty Twenty-Five.
 */

declare(strict_types=1);

if (!defined('ABSPATH')) {
    exit;
}

const BOLSCOBERTO_THEME_VERSION = '1.0.0';

function bolsocoberto_setup(): void
{
    add_theme_support('title-tag');
    add_theme_support('post-thumbnails');
    add_theme_support('custom-logo', [
        'height' => 64,
        'width' => 240,
        'flex-height' => true,
        'flex-width' => true,
    ]);
    register_nav_menus([
        'primary' => 'Principal',
    ]);
}
add_action('after_setup_theme', 'bolsocoberto_setup');

function bolsocoberto_enqueue(): void
{
    wp_enqueue_style(
        'bolsocoberto-parent',
        get_template_directory_uri() . '/style.css',
        [],
        wp_get_theme('twentytwentyfive')->get('Version')
    );
    wp_enqueue_style(
        'bolsocoberto',
        get_stylesheet_uri(),
        ['bolsocoberto-parent'],
        BOLSCOBERTO_THEME_VERSION
    );
    wp_enqueue_style(
        'bolsocoberto-content',
        get_stylesheet_directory_uri() . '/assets/content.css',
        ['bolsocoberto'],
        BOLSCOBERTO_THEME_VERSION
    );
}
add_action('wp_enqueue_scripts', 'bolsocoberto_enqueue');

function bolsocoberto_head_icons(): void
{
    $base = get_stylesheet_directory_uri() . '/assets';
    echo '<link rel="icon" href="' . esc_url($base . '/favicon.svg') . '" type="image/svg+xml">' . "\n";
    echo '<link rel="icon" href="' . esc_url($base . '/favicon-32.png') . '" sizes="32x32" type="image/png">' . "\n";
    echo '<link rel="apple-touch-icon" href="' . esc_url($base . '/apple-touch-icon.png') . '">' . "\n";
    echo '<link rel="manifest" href="' . esc_url($base . '/site.webmanifest') . '">' . "\n";
    echo '<meta name="theme-color" content="#0F7A4B">' . "\n";

    // O Rank Math já emite canonical. Dois canonicals na mesma página fazem o
    // Google descartar o sinal, então só emitimos quando ele não está no ar.
    if (!defined('RANK_MATH_VERSION')) {
        echo '<link rel="canonical" href="'
            . esc_url(is_singular() ? get_permalink() : home_url('/'))
            . '">' . "\n";
    }
}
add_action('wp_head', 'bolsocoberto_head_icons', 1);

/**
 * Uma unidade de anúncio. Devolve string vazia enquanto o AdSense não estiver
 * configurado, para o site não exibir buraco reservado sem preenchimento.
 */
function bolsocoberto_ad_unit(string $slot_option): string
{
    $publisher = trim((string) get_option('bolso_adsense_publisher_id', ''));
    $slot = trim((string) get_option($slot_option, ''));
    if ($publisher === '' || $slot === '') {
        return '';
    }

    return sprintf(
        '<div class="bc-ad"><span class="bc-ad__label">Publicidade</span>'
        . '<ins class="adsbygoogle" style="display:block" data-ad-client="%s" '
        . 'data-ad-slot="%s" data-ad-format="auto" data-full-width-responsive="true"></ins>'
        . '<script>(adsbygoogle=window.adsbygoogle||[]).push({});</script></div>',
        esc_attr($publisher),
        esc_attr($slot)
    );
}

/**
 * Insere anúncio antes do 2º e do 4º <h2>.
 *
 * A quebra de H2 é onde o leitor faz pausa, então converte melhor que anúncio
 * empurrado no meio do parágrafo. A altura reservada no CSS existe para o
 * carregamento do anúncio não empurrar o texto e destruir o CLS.
 */
function bolsocoberto_inject_ads(string $content): string
{
    if (!is_singular('post') || !in_the_loop() || !is_main_query() || is_feed()) {
        return $content;
    }

    // parts[0] é a abertura; parts[n] começa no n-ésimo <h2>. Inserir antes do
    // índice 2 e do 4 coloca o anúncio imediatamente antes do 2º e do 4º título.
    $parts = preg_split('#(?=<h2[\s>])#i', $content);
    if (!is_array($parts) || count($parts) < 3) {
        return $content;
    }

    $slots = [2 => 'bolso_adsense_slot_top', 4 => 'bolso_adsense_slot_mid'];
    $output = '';
    foreach ($parts as $index => $part) {
        if (isset($slots[$index])) {
            $output .= bolsocoberto_ad_unit($slots[$index]);
        }
        $output .= $part;
    }
    return $output;
}
add_filter('the_content', 'bolsocoberto_inject_ads', 20);

function bolsocoberto_adsense_loader(): void
{
    $publisher = trim((string) get_option('bolso_adsense_publisher_id', ''));
    if ($publisher === '' || is_admin()) {
        return;
    }
    printf(
        '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=%s" crossorigin="anonymous"></script>' . "\n",
        esc_attr(rawurlencode($publisher))
    );
}
add_action('wp_head', 'bolsocoberto_adsense_loader', 20);

function bolsocoberto_seed_menu(): void
{
    if (get_option('bolsocoberto_menu_seeded')) {
        return;
    }
    $menu_name = 'Principal Bolso';
    $menu = wp_get_nav_menu_object($menu_name);
    if (!$menu) {
        $menu_id = wp_create_nav_menu($menu_name);
    } else {
        $menu_id = (int) $menu->term_id;
    }

    // O seed roda de novo a cada higiene; sem limpar antes, cada execução
    // empilha uma cópia dos mesmos itens no menu.
    foreach (wp_get_nav_menu_items($menu_id) ?: [] as $existing_item) {
        wp_delete_post((int) $existing_item->ID, true);
    }

    $financas = get_category_by_slug('financas');
    $seguros = get_category_by_slug('seguros');

    $items = [];
    if ($financas) {
        $items[] = ['title' => 'Finanças', 'url' => get_category_link($financas)];
    }
    if ($seguros) {
        $items[] = ['title' => 'Seguros', 'url' => get_category_link($seguros)];
    }
    foreach (['sobre' => 'Sobre', 'contato' => 'Contato'] as $slug => $label) {
        $page = get_page_by_path($slug);
        if ($page instanceof WP_Post) {
            $items[] = ['title' => $label, 'url' => get_permalink($page)];
        }
    }

    foreach ($items as $item) {
        wp_update_nav_menu_item($menu_id, 0, [
            'menu-item-title' => $item['title'],
            'menu-item-url' => $item['url'],
            'menu-item-status' => 'publish',
            'menu-item-type' => 'custom',
        ]);
    }

    $locations = get_theme_mod('nav_menu_locations', []);
    $locations['primary'] = $menu_id;
    set_theme_mod('nav_menu_locations', $locations);
    update_option('bolsocoberto_menu_seeded', 1);
}
add_action('after_switch_theme', 'bolsocoberto_seed_menu');
