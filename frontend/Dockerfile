# syntax=docker/dockerfile:1.6
# Stage 1: Build frontend com Node
FROM node:20-alpine AS build

WORKDIR /app

# Copia package files primeiro para cache de dependências
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Copia código e builda
COPY . .
RUN npm run build

# Stage 2: Serve com Nginx
FROM nginx:1.25-alpine AS production

# Remove config padrão
RUN rm /etc/nginx/conf.d/default.conf

# Copia nginx config customizado
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copia build do frontend
COPY --from=build /app/dist /usr/share/nginx/html

# Healthcheck do Nginx
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD wget -qO- http://localhost:8080/health || exit 1

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
