FROM node:20-slim

WORKDIR /app

# Install dependencies from the lockfile first so this layer caches
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 8081

# docker-compose.yml overrides this with `--host lan`; kept here so the
# image still does something sensible if run standalone.
CMD ["npx", "expo", "start"]
