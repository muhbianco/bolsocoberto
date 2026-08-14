<?php
/**
 * Higiene pontual: Sobre, Privacidade, Rank Math, schema Organization.
 * Rodar dentro do container WordPress: php /tmp/wp-hygiene.php
 */
declare(strict_types=1);

if (php_sapi_name() !== 'cli') {
    fwrite(STDERR, "cli only\n");
    exit(1);
}

require '/var/www/html/wp-load.php';

function bolso_upsert_page(string $slug, string $title, string $content, string $status = 'publish'): int
{
    $existing = get_page_by_path($slug);
    $payload = [
        'post_title' => $title,
        'post_name' => $slug,
        'post_content' => $content,
        'post_status' => $status,
        'post_type' => 'page',
        'post_author' => 1,
    ];
    if ($existing instanceof WP_Post) {
        $payload['ID'] = $existing->ID;
        $id = wp_update_post($payload, true);
    } else {
        $id = wp_insert_post($payload, true);
    }
    if (is_wp_error($id)) {
        throw new RuntimeException($id->get_error_message());
    }
    return (int) $id;
}

$sobre = <<<'HTML'
<!-- wp:paragraph -->
<p>O Bolso Coberto é um portal brasileiro de finanças pessoais e seguros. A gente lê o que está acontecendo, checa o fato e escreve do zero — sem republicar matéria de outro site.</p>
<!-- /wp:paragraph -->
<!-- wp:paragraph -->
<p>Não somos corretora, banco nem consultoria. Nada aqui é recomendação personalizada de investimento ou de apólice. Se a decisão pesa no seu bolso, converse com um profissional habilitado.</p>
<!-- /wp:paragraph -->
<!-- wp:paragraph -->
<p>Contato: use o formulário quando estiver no ar, ou o e-mail do aviso de privacidade.</p>
<!-- /wp:paragraph -->
HTML;

bolso_upsert_page('sobre', 'Sobre', $sobre, 'publish');

$privacy = get_page_by_path('politica-de-privacidade');
if ($privacy instanceof WP_Post) {
    wp_update_post([
        'ID' => $privacy->ID,
        'post_status' => 'publish',
        'post_name' => 'privacidade',
        'post_title' => 'Privacidade',
    ]);
} else {
    $existing_priv = get_page_by_path('privacidade');
    if (!$existing_priv) {
        bolso_upsert_page(
            'privacidade',
            'Privacidade',
            '<!-- wp:paragraph --><p>Este site coleta o mínimo necessário para funcionar (logs técnicos e cookies essenciais). Não vendemos lista de leitores. Quando houver anúncios, a política será atualizada.</p><!-- /wp:paragraph -->',
            'publish'
        );
    } else {
        wp_update_post(['ID' => $existing_priv->ID, 'post_status' => 'publish']);
    }
}

require_once ABSPATH . 'wp-admin/includes/plugin.php';
require_once ABSPATH . 'wp-admin/includes/file.php';
require_once ABSPATH . 'wp-admin/includes/misc.php';
require_once ABSPATH . 'wp-admin/includes/class-wp-upgrader.php';
require_once ABSPATH . 'wp-admin/includes/plugin-install.php';

$plugin_file = 'seo-by-rank-math/rank-math.php';
if (!is_plugin_active($plugin_file)) {
    if (!file_exists(WP_PLUGIN_DIR . '/seo-by-rank-math/rank-math.php')) {
        $skin = new Automatic_Upgrader_Skin();
        $upgrader = new Plugin_Upgrader($skin);
        $ok = $upgrader->install('https://downloads.wordpress.org/plugin/seo-by-rank-math.latest-stable.zip');
        if ($ok !== true && !file_exists(WP_PLUGIN_DIR . '/seo-by-rank-math/rank-math.php')) {
            fwrite(STDERR, "Rank Math install failed\n");
        }
    }
    if (file_exists(WP_PLUGIN_DIR . '/seo-by-rank-math/rank-math.php')) {
        activate_plugin($plugin_file);
    }
}

update_option('blogdescription', 'Finanças e proteção, sem enrolação.');
update_option('rank_math_knowledgegraph_type', 'Organization');
update_option('rank_math_website_name', 'Bolso Coberto');

$htaccess = <<<'HTA'
# BEGIN WordPress
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]
RewriteBase /
RewriteRule ^index\.php$ - [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule . /index.php [L]
</IfModule>
# END WordPress
HTA;
file_put_contents('/var/www/html/.htaccess', $htaccess);

switch_theme('bolsocoberto');
if (function_exists('bolsocoberto_seed_menu')) {
    delete_option('bolsocoberto_menu_seeded');
    bolsocoberto_seed_menu();
}

$sobre_page = get_page_by_path('sobre');
$priv_page = get_page_by_path('privacidade');
echo "ok theme=" . wp_get_theme()->get_stylesheet() . "\n";
echo "sobre=" . ($sobre_page instanceof WP_Post ? (string) $sobre_page->ID : "0") . "\n";
echo "privacidade=" . ($priv_page instanceof WP_Post ? (string) $priv_page->ID : "0") . "\n";
