FROM node:24-alpine AS build

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/public ./public
COPY frontend/src ./src
COPY frontend/index.html ./
COPY frontend/vite.config.ts ./
COPY frontend/tsconfig*.json ./
COPY VERSION /app/VERSION

ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

FROM nginx:1.27-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80
