# Bolso Coberto

Portal de finanças e seguros — [bolsocoberto.com.br](https://bolsocoberto.com.br).
Editor interno em `post.bolsocoberto.com.br` (noindex).

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
