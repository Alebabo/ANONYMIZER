# syntax=docker/dockerfile:1
# OpenAnonymizer dashboard (Next.js standalone). Wird in GitHub Actions gebaut,
# nicht auf dem Server (next build braucht mehr RAM als der Server hat).
#   docker build -f deploy/dashboard.Dockerfile -t anonymizer-dashboard .
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_OUTPUT=standalone
RUN npx next build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0 \
    NODE_OPTIONS=--max-old-space-size=256
COPY --from=build --chown=node /app/.next/standalone ./
COPY --from=build --chown=node /app/.next/static ./.next/static
COPY --from=build --chown=node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
