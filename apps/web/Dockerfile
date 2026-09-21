# TextileOps web image (Next.js standalone server).
#
#   docker build -t textileops-web apps/web
#   docker run -e API_ORIGIN=https://api.example.com -p 3000:3000 textileops-web
#
# API_ORIGIN is read at request time by the same-origin proxy
# (app/api/v1/[...path]/route.ts), so one image runs against any API and the
# bundle contains neither the API's address nor any secret.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 textileops && adduser -S -u 10001 -G textileops textileops
COPY --from=build --chown=textileops:textileops /app/.next/standalone ./
COPY --from=build --chown=textileops:textileops /app/.next/static ./.next/static
USER textileops
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -qO- "http://127.0.0.1:${PORT}/login" >/dev/null || exit 1
CMD ["node", "server.js"]
