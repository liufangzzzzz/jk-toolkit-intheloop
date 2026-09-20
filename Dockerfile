FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM dependencies AS build
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.vinext ./.vinext
COPY --from=build /app/public ./public
COPY --from=build /app/app ./app
COPY --from=build /app/next.config.ts /app/vite.config.ts /app/tsconfig.json ./
EXPOSE 3000
CMD ["npm", "run", "start"]
