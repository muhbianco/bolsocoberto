<?php
/**
 * Higiene do site: páginas de confiança, Rank Math, mu-plugin de SEO, ads.txt e autor.
 *
 * Rodar dentro do container WordPress: php /tmp/wp-hygiene.php
 *
 * Variáveis de ambiente opcionais:
 *   ADSENSE_PUBLISHER_ID   pub-0000000000000000
 *   ADSENSE_SLOT_TOP       id da unidade antes do 2º H2
 *   ADSENSE_SLOT_MID       id da unidade antes do 4º H2
 *   AUTHOR_DISPLAY_NAME    nome que assina os textos
 *   AUTHOR_BIO             bio com credencial verificável
 *   AUTHOR_URL             perfil público (LinkedIn, por exemplo)
 *   CONTACT_EMAIL          e-mail exibido nas páginas de contato e privacidade
 */
declare(strict_types=1);

if (php_sapi_name() !== 'cli') {
    fwrite(STDERR, "cli only\n");
    exit(1);
}

require '/var/www/html/wp-load.php';

function bolso_env(string $key, string $fallback = ''): string
{
    $value = getenv($key);
    return is_string($value) && $value !== '' ? trim($value) : $fallback;
}

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

function bolso_p(string $text): string
{
    return "<!-- wp:paragraph -->\n<p>{$text}</p>\n<!-- /wp:paragraph -->\n";
}

function bolso_h(string $text, int $level = 2): string
{
    return "<!-- wp:heading {\"level\":{$level}} -->\n<h{$level}>{$text}</h{$level}>\n<!-- /wp:heading -->\n";
}

function bolso_nav_link(string $label, string $url): string
{
    return sprintf(
        '<!-- wp:navigation-link {"label":%s,"url":%s,"kind":"custom","isTopLevelLink":true} /-->' . "\n",
        wp_json_encode($label, JSON_UNESCAPED_UNICODE),
        wp_json_encode($url, JSON_UNESCAPED_SLASHES)
    );
}

function bolso_ul(array $items): string
{
    // Sem o wrapper wp:list-item o Gutenberg marca o bloco como inválido ao abrir.
    $li = implode('', array_map(
        static fn (string $i): string => "<!-- wp:list-item -->\n<li>{$i}</li>\n<!-- /wp:list-item -->\n",
        $items
    ));
    return "<!-- wp:list -->\n<ul class=\"wp-block-list\">\n{$li}</ul>\n<!-- /wp:list -->\n";
}

$contact_email = bolso_env('CONTACT_EMAIL', (string) get_option('admin_email'));
$author_name = bolso_env('AUTHOR_DISPLAY_NAME');
$author_bio = bolso_env('AUTHOR_BIO');
$author_url = bolso_env('AUTHOR_URL');

// ---------------------------------------------------------------- páginas

bolso_upsert_page(
    'sobre',
    'Sobre o Bolso Coberto',
    bolso_p('O Bolso Coberto é um portal brasileiro de finanças pessoais e seguros. A proposta é simples: pegar o que aconteceu, checar o dado na fonte que produziu o número e explicar o que aquilo muda no bolso de quem lê.')
    . bolso_h('Como trabalhamos')
    . bolso_p('Toda matéria começa por dados verificáveis. Quando o assunto envolve um indicador, buscamos o número direto no órgão responsável — Banco Central, IBGE, Susep, CVM, B3 — e não na intermediação de outro veículo. Os cálculos e as tabelas de simulação são feitos por nós e podem ser refeitos por qualquer leitor.')
    . bolso_p('Usamos ferramentas de automação para organizar apuração e acelerar a redação, e nenhum texto vai ao ar sem revisão humana de quem assina. A política editorial completa descreve o processo, incluindo o que fazemos quando erramos.')
    . bolso_h('O que não fazemos')
    . bolso_ul([
        'Não republicamos matéria de outro site.',
        'Não somos corretora, banco, seguradora nem consultoria de investimentos.',
        'Não damos recomendação personalizada de investimento nem de apólice.',
        'Não publicamos número que não conseguimos rastrear até a fonte original.',
    ])
    . bolso_p("Fale com a gente pelo e-mail <a href=\"mailto:{$contact_email}\">{$contact_email}</a> ou pela <a href=\"/contato/\">página de contato</a>.")
);

bolso_upsert_page(
    'contato',
    'Contato',
    bolso_p('Correção, sugestão de pauta, direito de resposta ou proposta comercial: escreva e a gente responde.')
    . bolso_p("E-mail: <a href=\"mailto:{$contact_email}\">{$contact_email}</a>")
    . bolso_h('Correções')
    . bolso_p('Se você encontrou um dado errado em alguma matéria, mande o link e a informação correta. Erro confirmado é corrigido no próprio texto, com nota informando o que mudou e quando.')
    . bolso_h('Prazo')
    . bolso_p('Respondemos em até cinco dias úteis. Pedido de correção tem prioridade.')
);

bolso_upsert_page(
    'politica-editorial',
    'Política editorial',
    bolso_p('Este documento descreve como o conteúdo do Bolso Coberto é produzido, revisado e corrigido.')
    . bolso_h('Origem dos dados')
    . bolso_p('Toda informação numérica sai de fonte primária identificada: o órgão, a pesquisa e o período de referência aparecem no texto ou na seção "Dados e referências". Quando a pauta chega por uma reportagem de outro veículo, o crédito de apuração é dado, mas o dado é conferido na origem e o texto é escrito do zero.')
    . bolso_h('Uso de automação')
    . bolso_p('Usamos modelos de linguagem em parte do processo, com uma restrição própria: o redator automático recebe apenas a lista de fatos apurados, nunca o texto original da fonte. Isso existe para impedir paráfrase. Antes da publicação, cada número passa por uma checagem que compara o rascunho com a lista de fatos, e o texto passa por uma medida automática de similaridade contra as fontes. Nada é publicado sem leitura e aprovação humana.')
    . bolso_h('Independência e publicidade')
    . bolso_p('O site é sustentado por publicidade e, quando houver, por links de parceria devidamente sinalizados. Anunciante não decide pauta, não lê texto antes da publicação e não tem direito a veto. Conteúdo patrocinado, se existir, será identificado como tal no topo da página.')
    . bolso_h('Correções')
    . bolso_p('Erro identificado é corrigido no próprio texto, com nota ao pé informando o que mudou e a data. Não apagamos matéria para esconder erro.')
    . bolso_h('Limite do conteúdo')
    . bolso_p('O que publicamos é informação, não consultoria. Nenhum texto considera a sua situação individual. Decisão que pesa no orçamento merece conversa com profissional habilitado e registrado no órgão competente.')
);

bolso_upsert_page(
    'aviso-legal',
    'Aviso legal',
    bolso_h('Natureza do conteúdo')
    . bolso_p('O Bolso Coberto publica conteúdo jornalístico e educativo sobre finanças pessoais e seguros. As informações têm caráter geral e informativo e não constituem recomendação, oferta, solicitação ou aconselhamento de investimento, de crédito ou de contratação de seguro.')
    . bolso_h('Sem relação de consultoria')
    . bolso_p('O Bolso Coberto não é instituição financeira, corretora de valores, corretora de seguros, consultor de valores mobiliários nem analista credenciado. Não mantemos relação de consultoria com nossos leitores e não temos acesso à sua situação patrimonial, ao seu perfil de risco ou aos seus objetivos.')
    . bolso_h('Rentabilidade e simulações')
    . bolso_p('Simulações publicadas são exercícios matemáticos sobre premissas explicitadas no próprio texto e servem para ilustrar ordem de grandeza. Rentabilidade passada não garante rentabilidade futura. Condições de produtos financeiros e de seguros mudam sem aviso, e cabe ao leitor conferir os termos vigentes com a instituição.')
    . bolso_h('Links externos')
    . bolso_p('Links para sites de terceiros são oferecidos como referência. Não controlamos e não respondemos pelo conteúdo, pelas práticas de privacidade ou pela disponibilidade desses sites.')
    . bolso_h('Limitação de responsabilidade')
    . bolso_p('Nos esforçamos para publicar informação correta e atualizada, mas não garantimos exatidão, completude ou atualidade permanente. Decisões tomadas com base no conteúdo deste site são de responsabilidade exclusiva de quem as toma.')
);

$privacidade = bolso_p('Esta política explica quais dados o Bolso Coberto coleta, por que coleta e o que você pode exigir. Ela segue a Lei Geral de Proteção de Dados (Lei 13.709/2018).')
    . bolso_h('Dados que coletamos')
    . bolso_ul([
        'Dados técnicos de acesso: endereço IP, tipo de navegador, páginas visitadas e horário, registrados para segurança e para medir audiência.',
        'Cookies essenciais, necessários para o site funcionar.',
        'Cookies de publicidade e de medição, quando você consente.',
    ])
    . bolso_h('Publicidade e cookies de terceiros')
    . bolso_p('Este site exibe anúncios. Fornecedores terceiros, incluindo o Google, usam cookies para exibir anúncios com base em visitas anteriores suas a este e a outros sites. O uso de cookies de publicidade pelo Google permite que ele e seus parceiros veiculem anúncios com base nessas visitas.')
    . bolso_p('Você pode desativar a publicidade personalizada nas <a href="https://www.google.com/settings/ads" rel="nofollow noopener" target="_blank">Configurações de anúncios do Google</a>. Também é possível desativar cookies de terceiros em <a href="https://www.aboutads.info/choices/" rel="nofollow noopener" target="_blank">aboutads.info</a>.')
    . bolso_h('Base legal')
    . bolso_p('Tratamos dados técnicos com base no legítimo interesse de operar e proteger o site, e dados de publicidade personalizada e medição com base no seu consentimento, que pode ser retirado a qualquer momento.')
    . bolso_h('Seus direitos')
    . bolso_p('A LGPD garante a você confirmação do tratamento, acesso, correção, anonimização, portabilidade, informação sobre compartilhamento e revogação do consentimento. Para exercer qualquer um deles, escreva para <a href="mailto:' . $contact_email . '">' . $contact_email . '</a>.')
    . bolso_h('O que não fazemos')
    . bolso_p('Não vendemos sua lista de leitura, não comercializamos base de e-mails e não pedimos dado sensível para entregar conteúdo.')
    . bolso_h('Retenção')
    . bolso_p('Logs técnicos são mantidos pelo prazo necessário à segurança e às obrigações legais, e descartados depois disso.');

$legacy_privacy = get_page_by_path('politica-de-privacidade');
if ($legacy_privacy instanceof WP_Post) {
    wp_update_post([
        'ID' => $legacy_privacy->ID,
        'post_name' => 'privacidade',
        'post_title' => 'Privacidade',
        'post_content' => $privacidade,
        'post_status' => 'publish',
    ]);
} else {
    bolso_upsert_page('privacidade', 'Privacidade', $privacidade);
}

// ---------------------------------------------------------------- Rank Math

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

// ---------------------------------------------------------------- mu-plugin

$mu_dir = WP_CONTENT_DIR . '/mu-plugins';
$mu_source = '/tmp/mu-plugins/bolsocoberto-seo.php';
if (file_exists($mu_source)) {
    if (!is_dir($mu_dir)) {
        wp_mkdir_p($mu_dir);
    }
    if (!copy($mu_source, $mu_dir . '/bolsocoberto-seo.php')) {
        fwrite(STDERR, "mu-plugin copy failed\n");
    }
} else {
    fwrite(STDERR, "mu-plugin não encontrado em {$mu_source}; envie antes de rodar\n");
}

// ---------------------------------------------------------------- AdSense

$publisher = bolso_env('ADSENSE_PUBLISHER_ID');
if ($publisher !== '') {
    update_option('bolso_adsense_publisher_id', $publisher);
    update_option('bolso_adsense_slot_top', bolso_env('ADSENSE_SLOT_TOP'));
    update_option('bolso_adsense_slot_mid', bolso_env('ADSENSE_SLOT_MID'));
    // Arquivo real na raiz: é o que o rastreador do AdSense procura primeiro.
    file_put_contents(
        '/var/www/html/ads.txt',
        "google.com, {$publisher}, DIRECT, f08c47fec0942fa0\n"
    );
}

// ---------------------------------------------------------------- autor

if ($author_name !== '' || $author_bio !== '') {
    $payload = ['ID' => 1];
    if ($author_name !== '') {
        $payload['display_name'] = $author_name;
        $payload['nickname'] = $author_name;
    }
    if ($author_bio !== '') {
        $payload['description'] = $author_bio;
    }
    if ($author_url !== '') {
        $payload['user_url'] = $author_url;
    }
    $updated = wp_update_user($payload);
    if (is_wp_error($updated)) {
        fwrite(STDERR, 'autor: ' . $updated->get_error_message() . "\n");
    }
}

// ---------------------------------------------------------------- rewrite

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

// ------------------------------------------------------------- categorias

// O editor só associa a categoria se ela já existir: ele busca pelo slug e
// desiste em silêncio. Sem isto, matéria de seguros nasce sem categoria.
foreach (['financas' => 'Finanças', 'seguros' => 'Seguros'] as $slug => $name) {
    if (!get_category_by_slug($slug)) {
        wp_insert_term($name, 'category', ['slug' => $slug]);
    }
}

// -------------------------------------------------------------- navegação

/**
 * O bloco wp:navigation do cabeçalho não tem `ref`: o WordPress adota o post
 * wp_navigation publicado mais recentemente e, quando não existe nenhum, cai
 * na lista automática de páginas — foi assim que Aviso legal e Privacidade
 * foram parar no topo do site. Manter um único post torna o menu previsível.
 */
$nav_blocks = '';
foreach (['financas' => 'Finanças', 'seguros' => 'Seguros'] as $slug => $label) {
    $term = get_category_by_slug($slug);
    if ($term instanceof WP_Term) {
        $nav_blocks .= bolso_nav_link($label, get_category_link($term));
    }
}
foreach (['sobre' => 'Sobre', 'contato' => 'Contato'] as $slug => $label) {
    $page = get_page_by_path($slug);
    if ($page instanceof WP_Post) {
        $nav_blocks .= bolso_nav_link($label, get_permalink($page));
    }
}

$nav_slug = 'menu-principal';
$nav_id = 0;
$nav_removed = 0;
$nav_existing = get_posts([
    'post_type' => 'wp_navigation',
    'post_status' => ['publish', 'draft'],
    'numberposts' => -1,
    'orderby' => 'ID',
    'order' => 'ASC',
]);
foreach ($nav_existing as $nav_post) {
    if ($nav_id === 0 && $nav_post->post_name === $nav_slug) {
        $nav_id = (int) $nav_post->ID;
        continue;
    }
    wp_delete_post((int) $nav_post->ID, true);
    $nav_removed++;
}

$nav_now = current_time('mysql');
$nav_payload = [
    'post_title' => 'Menu principal',
    'post_name' => $nav_slug,
    'post_content' => $nav_blocks,
    'post_status' => 'publish',
    'post_type' => 'wp_navigation',
    // Data renovada a cada execução: é o critério que o core usa para escolher
    // qual navegação assume quando o bloco não aponta para um id.
    'post_date' => $nav_now,
    'post_date_gmt' => get_gmt_from_date($nav_now),
];
if ($nav_id > 0) {
    $nav_payload['ID'] = $nav_id;
    $nav_result = wp_update_post($nav_payload, true);
} else {
    $nav_result = wp_insert_post($nav_payload, true);
}
if (is_wp_error($nav_result)) {
    fwrite(STDERR, 'menu: ' . $nav_result->get_error_message() . "\n");
    $nav_id = 0;
} else {
    $nav_id = (int) $nav_result;
}

foreach (['sobre', 'contato', 'privacidade', 'aviso-legal', 'politica-editorial'] as $slug) {
    $page = get_page_by_path($slug);
    echo $slug . '=' . ($page instanceof WP_Post ? (string) $page->ID : '0') . "\n";
}
echo 'theme=' . wp_get_theme()->get_stylesheet() . "\n";
echo 'menu=' . ($nav_id > 0 ? (string) $nav_id : 'falhou')
    . ' (removidos=' . (string) $nav_removed . ")\n";
echo 'adsense=' . ($publisher !== '' ? 'configurado' : 'pendente') . "\n";
echo 'mu-plugin=' . (file_exists($mu_dir . '/bolsocoberto-seo.php') ? 'ok' : 'faltando') . "\n";
