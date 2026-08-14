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
    echo '<link rel="canonical" href="' . esc_url(is_singular() ? get_permalink() : home_url('/')) . '">' . "\n";
}
add_action('wp_head', 'bolsocoberto_head_icons', 1);

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

    $financas = get_category_by_slug('financas');
    $seguros = get_category_by_slug('seguros');
    $sobre = get_page_by_path('sobre');

    $items = [];
    if ($financas) {
        $items[] = ['title' => 'Finanças', 'url' => get_category_link($financas)];
    }
    if ($seguros) {
        $items[] = ['title' => 'Seguros', 'url' => get_category_link($seguros)];
    }
    if ($sobre instanceof WP_Post) {
        $items[] = ['title' => 'Sobre', 'url' => get_permalink($sobre)];
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
