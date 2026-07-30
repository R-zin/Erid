# Multi-stage build for the dashboard.
# Stage 1: build the SPA to static assets with Vite. Stage 2: serve them via
# nginx, which also proxies /api (REST + WebSocket) to the `api` service.

# ---- build stage -------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app

# Leverage the lockfile for reproducible builds and cache-friendly layering.
COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.js ./
COPY src ./src
RUN npm run build   # emits web/dist

# ---- serve stage -------------------------------------------------------------
FROM nginx:1.27-alpine

# Reverse-proxy config: server block + the http-context WebSocket upgrade map.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx.websocket.conf /etc/nginx/conf.d/websocket.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
