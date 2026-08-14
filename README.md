# Bolso Coberto

Portal de finanças e seguros — [bolsocoberto.com.br](https://bolsocoberto.com.br).
Editor interno em `post.bolsocoberto.com.br` (noindex).

## Como o editor produz texto

A notícia é **gancho**, não produto. O pipeline roda em três passagens no Gemini,
e a separação entre elas é a parte que importa:

1. **Extração** (`temp 0.1`) — lê as URLs e devolve uma trilha de fatos: afirmação,
   valor, unidade, período, quem produziu o dado e qual é a **fonte primária**.
2. **Redação** (`temp 0.5`) — recebe **apenas a trilha de fatos**, nunca a prosa
   original. Parafrasear frase a frase deixa de ser possível por construção, e não
   por instrução no prompt.
3. **Checagem** (`temp 0.0`) — compara o rascunho com a trilha e aponta todo número
   sem lastro ou distorcido.

Fora do modelo, em código determinístico:

- **Similaridade de 8-gramas** contra o texto de cada fonte (`app/services/similarity.py`).
  Acima de `SIMILARITY_BLOCK_THRESHOLD` o botão de publicar trava.
- **Dados oficiais** do SGS/Banco Central e tabelas de rendimento calculadas em
  Python (`app/services/enrich.py`). Número calculado não alucina, e nenhuma das
  fontes de pauta publica aquele recorte — é o valor original que o Google cobra.
- **Capa 1200×675** com gráfico do indicador (`app/services/image.py`), requisito
  do Google Discover.

Tipos de pauta: `noticia` (600–900 palavras), `explicativo` (1100–1600, o padrão) e
`guia` evergreen (1800–2500, dispensa URL e é o que sustenta a receita).

## Política de fontes

Esconder a origem não engana o Google: ele rastreou o veículo antes, tem os
timestamps e calcula quase-duplicata. O que a omissão custa é real — sinal de
confiança em nicho YMYL, cobertura do art. 46 da Lei 9.610/98 e link de saída para
autoridade. Então o rodapé tem **duas camadas com papéis diferentes**:

| Camada | O que entra | Link |
|---|---|---|
| `Dados e referências` | Órgão que produziu o dado: IBGE, BCB, Susep, CVM, B3, ANS | visível, **dofollow** |
| `Apuração` | Veículo de imprensa, pelo **nome da casa** | uma linha, **nofollow**, 1 por domínio |

A manchete do concorrente nunca é reproduzida, e dois links para o mesmo veículo
viram um. A montagem é feita em código (`app/services/sources.py`), não pelo modelo,
justamente para a política não depender de o prompt ser obedecido.

## Trava de publicação

`Aplicar rascunho no WP` fica desabilitado enquanto houver afirmação sem lastro ou
similaridade acima do limite. Em guia evergreen a checagem é aviso, não trava, porque
ali o texto é conhecimento estável de domínio e não apuração. A trilha de fatos fica
gravada em `editor_jobs.fact_ledger_json` como prova de apuração.

## Layout (mesmo padrão do `api-agents`)

| Arquivo | Função |
|---|---|
| `Dockerfile` | multi-stage Python 3.12, user 1001, HEALTHCHECK `/health/live` |
| `build.sh` / `build.ps1` | tag local + `muhrilobianco/bolsocoberto:latest` |
| `docker-stack.yml` | stack **editor** (`bolso_editor` + worker), secrets `""` |
| `wordpress-stack.yml` | stack WordPress já no Portainer (`bolsocoberto`) |
| `app/` | FastAPI + worker de pauta |
| `theme/bolsocoberto` | tema filho do Twenty Twenty-Five |
| `brand/` | tokens, SVG, ícones, OG |
| `dns/` | zonas GoDaddy de referência |

Na VPS o build **não** usa `./build.sh prod` (login interativo). `git pull` + `docker build` + `tag` + `push`.

O YAML operacional é o **Editor do Portainer**. Este git não leva senha. Não colar o YAML vazio por cima da stack de prod.

## DNS

CNAME `post` → `manager.bolsocoberto.com.br.` (zona `.com.br`). Sem AAAA.

## OAuth / WP

No Google Cloud: redirect `https://post.bolsocoberto.com.br/auth/callback`. Allowlist só `muhbianco@gmail.com`.

No WordPress: Application Password do admin → `WP_APP_USER` / `WP_APP_PASSWORD` no Portainer.

## Higiene do WordPress

Enviar os dois arquivos para o container e rodar:

```bash
docker cp scripts/wp-hygiene.php <container>:/tmp/wp-hygiene.php
docker cp scripts/mu-plugins <container>:/tmp/mu-plugins
docker exec -e CONTACT_EMAIL=... -e AUTHOR_DISPLAY_NAME=... -e AUTHOR_BIO=... \
  <container> php /tmp/wp-hygiene.php
```

O script é idempotente: cria as páginas de confiança (Sobre, Contato, Privacidade,
Aviso legal, Política editorial), instala o Rank Math e o mu-plugin de SEO, grava
`ads.txt` e ajusta o autor. Variáveis aceitas estão no cabeçalho do arquivo.

O mu-plugin registra os metadados do Rank Math na REST — **sem ele o editor publica
sem título e sem descrição de SEO**, porque o WordPress descarta meta não registrada
em silêncio.

## Checklist antes de pedir AdSense

Requisitos de 2026, na ordem em que travam a aprovação:

- [ ] 20 a 30 textos originais publicados, com profundidade real
- [ ] Byline com pessoa identificável e página de autor com bio verificável
- [ ] Sobre, Contato, Privacidade e Aviso legal preenchidas (o script cria)
- [ ] Privacidade citando cookies do Google e direitos da LGPD (o script escreve)
- [ ] `ads.txt` respondendo em `/ads.txt`
- [ ] Sitemap do Rank Math enviado ao Search Console e páginas indexadas
- [ ] `max-image-preview:large` no `<head>` (o mu-plugin garante)
- [ ] Imagem destacada de 1200px em todo post (o editor gera)

Depois da aprovação, preencher `ADSENSE_PUBLISHER_ID`, `ADSENSE_SLOT_TOP` e
`ADSENSE_SLOT_MID` e rodar a higiene de novo. Os slots só aparecem no site quando
esses valores existem, e o CSS reserva a altura antes para o anúncio não empurrar o
texto e destruir o CLS.
