# syntax=docker/dockerfile:1
FROM node:26.13.1-alpine AS build
WORKDIR /app
ENV npm_config_audit=false npm_config_fund=false
RUN npm install --global npm@12.2.2 --no-audit --no-fund
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx/nginx-unprivileged:1.30.6-alpine AS runtime
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --start-interval=1s --timeout=3s --start-period=10s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/health/web && \
    wget -q -O /dev/null http://127.0.0.1:8080/health/ready || exit 1
ENTRYPOINT ["nginx", "-g", "daemon off;"]
