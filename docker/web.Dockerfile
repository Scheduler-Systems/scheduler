# Next.js web app in dev mode (emulator-wired). ⚠️ unverified — see docker-compose.yml.
FROM node:20-bookworm-slim
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm install
COPY apps/web ./
EXPOSE 3000
CMD ["npm", "run", "dev"]
