FROM docker.io/library/node:24-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 ELECTRON_SKIP_BINARY_DOWNLOAD=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 make g++ ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build && node scripts/build-server.mjs

FROM docker.io/library/node:24-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000 \
    LH_DATA_DIR=/app/data \
    LH_AUTH_FILE=/app/secrets/auth.json \
    CHROME_PATH=/usr/bin/chromium

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       chromium ca-certificates fonts-dejavu-core fonts-noto-color-emoji tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/.next/standalone ./
RUN mkdir -p /app/data /app/secrets
EXPOSE 3000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "server.js"]
