# BOE Analytics web — Next.js standalone server on 3000.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# next.config.mjs sets output:"standalone", which traces the server's actual
# imports — the runtime stage then carries those instead of all of node_modules.
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=build /app/.next/standalone ./
# Static assets are deliberately outside the standalone trace; without this the
# app serves 404s for its own CSS and JS chunks.
COPY --from=build /app/.next/static ./.next/static

# Next touches .next/cache at runtime even without ISR; the copied tree is
# root-owned, so give the runtime user somewhere to write before dropping to it.
RUN mkdir -p .next/cache && chown -R node:node .next

USER node
EXPOSE 3000

# Node 22 has global fetch, so no curl in the image for this either.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
