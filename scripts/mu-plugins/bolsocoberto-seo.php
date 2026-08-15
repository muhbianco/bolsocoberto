<?php
/**
 * Plugin Name: Bolso Coberto — SEO e monetização
 * Description: Expõe os metadados do Rank Math na REST, publica ads.txt e emite schema de FAQ.
 * Version: 1.2.1
 *
 * Vive em mu-plugins porque o editor externo depende disso para gravar SEO:
 * se ficasse no tema, trocar de tema quebraria a publicação.
 */

declare(strict_types=1);

if (!defined('ABSPATH')) {
    exit;
}

const BOLSO_SEO_META_KEYS = [
    'rank_math_title',
    'rank_math_description',
    'rank_math_focus_keyword',
];

/**
 * Sem show_in_rest o WordPress descarta silenciosamente o campo meta enviado
 * pelo editor, e o post sai sem título e sem descrição de SEO.
 */
function bolso_seo_register_meta(): void
{
    foreach (['post', 'page'] as $type) {
        foreach (BOLSO_SEO_META_KEYS as $key) {
            register_post_meta($type, $key, [
                'type' => 'string',
                'single' => true,
                'show_in_rest' => true,
                'sanitize_callback' => 'wp_strip_all_tags',
                'auth_callback' => static fn (): bool => current_user_can('edit_posts'),
            ]);
        }
    }
}
add_action('init', 'bolso_seo_register_meta');

/**
 * O Discover só monta card grande com este valor. O core já usa este padrão em
 * site público, mas deixamos explícito para não depender da configuração.
 */
const BOLSO_SEO_MIN_TAG_POSTS = 5;

/**
 * Arquivo de tag com dois ou três posts é página fina, e página fina em volume
 * é exatamente o que derruba análise de AdSense e ranking em core update.
 * O limite se resolve sozinho conforme a tag acumula matéria.
 */
function bolso_seo_should_noindex(): bool
{
    if (is_date() || is_search()) {
        return true;
    }
    if (!is_tag()) {
        return false;
    }
    $term = get_queried_object();
    return $term instanceof WP_Term && $term->count < BOLSO_SEO_MIN_TAG_POSTS;
}

function bolso_seo_robots(array $robots): array
{
    $robots['max-image-preview'] = 'large';
    $robots['max-snippet'] = -1;
    $robots['max-video-preview'] = -1;

    if (bolso_seo_should_noindex()) {
        $robots['noindex'] = true;
        unset($robots['index']);
    }

    return $robots;
}
add_filter('wp_robots', 'bolso_seo_robots', 20);

/**
 * O Rank Math monta a própria meta robots e ignora o filtro do core, então a
 * mesma decisão precisa ser repetida no filtro dele.
 */
function bolso_seo_rank_math_robots(array $robots): array
{
    $robots['max-image-preview'] = 'max-image-preview:large';
    if (bolso_seo_should_noindex()) {
        $robots['index'] = 'noindex';
    }
    return $robots;
}
add_filter('rank_math/frontend/robots', 'bolso_seo_rank_math_robots');

/**
 * ads.txt virtual: se o arquivo físico sumir num redeploy, o AdSense continua
 * encontrando a declaração e o inventário não fica sem monetizar.
 */
function bolso_seo_ads_txt(): void
{
    if (!isset($_SERVER['REQUEST_URI'])) {
        return;
    }
    $path = parse_url((string) $_SERVER['REQUEST_URI'], PHP_URL_PATH);
    if ($path !== '/ads.txt') {
        return;
    }
    if (file_exists(ABSPATH . 'ads.txt')) {
        return;
    }
    $publisher = trim((string) get_option('bolso_adsense_publisher_id', ''));
    if ($publisher === '') {
        return;
    }
    header('Content-Type: text/plain; charset=utf-8');
    echo 'google.com, ' . $publisher . ', DIRECT, f08c47fec0942fa0' . "\n";
    exit;
}
add_action('init', 'bolso_seo_ads_txt', 1);

/**
 * Schema de FAQ a partir do bloco que o editor gera.
 * O Article/NewsArticle fica por conta do Rank Math — emitir os dois duplicaria.
 */
function bolso_seo_faq_schema(): void
{
    if (!is_singular('post')) {
        return;
    }
    $post = get_post();
    if (!$post instanceof WP_Post) {
        return;
    }
    if (!str_contains($post->post_content, 'bc-faq-item')) {
        return;
    }

    $pattern = '#<div class="bc-faq-item">\s*<h3>(.*?)</h3>\s*<p>(.*?)</p>\s*</div>#si';
    if (!preg_match_all($pattern, $post->post_content, $matches, PREG_SET_ORDER)) {
        return;
    }

    $entities = [];
    foreach ($matches as $match) {
        $question = trim(wp_strip_all_tags($match[1]));
        $answer = trim(wp_strip_all_tags($match[2]));
        if ($question === '' || $answer === '') {
            continue;
        }
        $entities[] = [
            '@type' => 'Question',
            'name' => $question,
            'acceptedAnswer' => ['@type' => 'Answer', 'text' => $answer],
        ];
    }
    if ($entities === []) {
        return;
    }

    $schema = [
        '@context' => 'https://schema.org',
        '@type' => 'FAQPage',
        'mainEntity' => $entities,
    ];
    echo "\n<script type=\"application/ld+json\">"
        . wp_json_encode($schema, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)
        . "</script>\n";
}
add_action('wp_footer', 'bolso_seo_faq_schema');

/**
 * Página estática não é Article. Rank Math defaulta Posts e Pages para o mesmo
 * snippet; sem este filtro, Sobre/Contato saem como BlogPosting no JSON-LD.
 *
 * @param array<string, mixed> $data
 * @param mixed                $jsonld
 * @return array<string, mixed>
 */
function bolso_seo_page_schema(array $data, $jsonld): array
{
    if (!is_singular('page')) {
        return $data;
    }

    foreach (['Article', 'article', 'BlogPosting', 'NewsArticle', 'richSnippet'] as $key) {
        unset($data[$key]);
    }

    $slug = get_post_field('post_name', get_queried_object_id());
    $type = match ($slug) {
        'sobre' => 'AboutPage',
        'contato' => 'ContactPage',
        default => 'WebPage',
    };

    if (isset($data['WebPage']) && is_array($data['WebPage'])) {
        $data['WebPage']['@type'] = $type;
        return $data;
    }

    $permalink = get_permalink();
    $data['WebPage'] = [
        '@type' => $type,
        '@id' => $permalink . '#webpage',
        'url' => $permalink,
        'name' => get_the_title(),
        'inLanguage' => 'pt-BR',
        'isPartOf' => ['@id' => home_url('/#website')],
    ];
    return $data;
}
add_filter('rank_math/json_ld', 'bolso_seo_page_schema', 99, 2);

/**
 * Rank Math com snippet "off" nas páginas não chama json_ld — então o tipo
 * certo precisa ser emitido aqui, senão Sobre/Contato saem sem schema nenhum.
 */
function bolso_seo_page_jsonld(): void
{
    if (!is_singular('page')) {
        return;
    }
    $slug = get_post_field('post_name', get_queried_object_id());
    $type = match ($slug) {
        'sobre' => 'AboutPage',
        'contato' => 'ContactPage',
        default => 'WebPage',
    };
    $permalink = get_permalink();
    $schema = [
        '@context' => 'https://schema.org',
        '@type' => $type,
        '@id' => $permalink . '#webpage',
        'url' => $permalink,
        'name' => get_the_title(),
        'inLanguage' => 'pt-BR',
        'isPartOf' => ['@id' => home_url('/#website')],
    ];
    $description = trim((string) get_post_meta(get_queried_object_id(), 'rank_math_description', true));
    if ($description !== '') {
        $schema['description'] = $description;
    }
    echo "\n<script type=\"application/ld+json\">"
        . wp_json_encode($schema, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)
        . "</script>\n";
}
add_action('wp_footer', 'bolso_seo_page_jsonld');
