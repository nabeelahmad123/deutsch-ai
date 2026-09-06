# Deployment

The live instance runs on a single DigitalOcean droplet with Docker Compose.
CI/CD is GitHub Actions: **push to `main` -> full test suite -> build image ->
push to GHCR -> deploy over SSH -> health-check.**

```
GitHub push (main)
      │
      ▼
 .github/workflows/cd.yml
   1. ci      – reuses ci.yml (core + full test jobs)
   2. build   – docker build backend/Dockerfile, push
                ghcr.io/nabeelahmad123/deutsch-ai:{latest,<sha>}
   3. deploy  – scp deploy/*.yml + Caddyfile to the droplet,
                then ssh: docker compose pull && up -d && curl /health
      │
      ▼
 droplet /opt/learn-german
   docker-compose.prod.yml → postgres · backend(API+SPA) ·
   learning-mcp · secondary-mcp · caddy(TLS)
```

## One-time server bootstrap

Done once as `root` on a fresh Ubuntu 24.04 droplet:

```bash
apt update && apt -y upgrade
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
adduser --disabled-password --gecos "" deploy && usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
curl -fsSL https://get.docker.com | sh && usermod -aG docker deploy
mkdir -p /opt/learn-german && chown deploy:deploy /opt/learn-german
```

Then, as `deploy`, create `/opt/learn-german/.env` from [`env.example`](env.example)
with a real `POSTGRES_PASSWORD` and `ANTHROPIC_API_KEY`.

## GitHub Actions secrets

Repo -> Settings -> Secrets and variables -> Actions:

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | droplet public IP |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | private key of a dedicated deploy keypair (public half in `deploy`'s `~/.ssh/authorized_keys`) |
| `GHCR_PAT` | GitHub PAT (classic) with scope `read:packages` — lets the droplet pull the private image |

Generate the deploy keypair locally and register it:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/deutsch_deploy -N "" -C "gh-actions-deploy"
ssh-copy-id -i ~/.ssh/deutsch_deploy.pub deploy@<DROPLET_IP>
pbcopy < ~/.ssh/deutsch_deploy      # paste into the DEPLOY_SSH_KEY secret
```

## First deploy

Merge this branch to `main` (or hit **Run workflow** on the CD action). The
`deploy` job seeds ~4k words on first boot, so it polls `/health` for up to
150 s.

## Manual operations on the droplet

```bash
cd /opt/learn-german
docker compose -f docker-compose.prod.yml --env-file .env ps
docker compose -f docker-compose.prod.yml --env-file .env logs -f backend

# roll back to a previous image
export IMAGE=ghcr.io/nabeelahmad123/deutsch-ai:<older-sha>
docker compose -f docker-compose.prod.yml --env-file .env up -d
```

## HTTPS

Set `SITE_ADDRESS` in `.env` to either `<DROPLET_IP>.nip.io` (free cert, no
domain) or your real domain (add a DNS `A` record to the droplet first), then
re-run the deploy. Caddy fetches the Let's Encrypt certificate automatically.
