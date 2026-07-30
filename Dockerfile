FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY edith ./edith
COPY main.py ./
COPY docker-entrypoint.sh ./

RUN pip install --no-cache-dir -e . \
    && playwright install --with-deps chromium

# Node/npm for the monid CLI (edith/tools/monid.py shells out to it) — Debian's
# own nodejs/npm packages lag far behind current LTS, so use NodeSource's setup
# script for a real current version instead. Also doubles as npx for any
# user-added npx-launched MCP server (edith/tools/mcp_client.py). uv/uvx
# installed in the same layer (before curl is purged) as the other common MCP
# server launcher (e.g. `uvx some-mcp-package`) — installed to a fixed path
# rather than relying on the installer's own shell-profile wiring, which
# doesn't apply to non-interactive containers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @monid-ai/cli \
    && curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh \
    && apt-get purge -y curl \
    && rm -rf /var/lib/apt/lists/*

RUN chmod +x docker-entrypoint.sh

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["./docker-entrypoint.sh"]
