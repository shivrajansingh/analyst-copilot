# The UI: Vite build, served by nginx, proxying /api to the api container.
#
# Nothing about the API's address is baked into the bundle. The client always
# calls same-origin `/api` (see ui/src/api/client.ts), nginx forwards it, and
# the same image therefore runs unchanged in development, staging and
# production -- and CORS never enters the deployed path at all.

# ------------------------------------------------------------------ build ---
FROM node:22-alpine AS build

WORKDIR /app

# The lockfile alone first: dependencies change rarely, source changes
# constantly, and `npm ci` is the slow half of this build.
COPY ui/package.json ui/package-lock.json ./
RUN npm ci

COPY ui/ ./
# `npm run build` is `tsc -b && vite build`, so a type error fails the image
# rather than shipping a bundle nobody typechecked.
RUN npm run build

# ------------------------------------------------------------------ serve ---
FROM nginx:1.27-alpine AS runtime

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# wget is in the busybox nginx:alpine ships, so this costs nothing.
HEALTHCHECK --interval=15s --timeout=4s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
