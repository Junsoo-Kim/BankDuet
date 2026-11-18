FROM node:24-bookworm-slim AS build
ENV SCARF_ANALYTICS=false
WORKDIR /web
COPY package*.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
COPY --from=build /web/node_modules/swagger-ui-dist/swagger-ui-bundle.js /web/node_modules/swagger-ui-dist/swagger-ui.css /web/node_modules/swagger-ui-dist/favicon-32x32.png /usr/share/nginx/html/swagger/
