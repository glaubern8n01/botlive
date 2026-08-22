# Imagem do painel: build do Vite + o server.mjs que serve /api.
#
# Existe porque em 19/08 o painel foi para producao como imagem so-nginx. O
# estatico subia, mas /api/* caia no try_files e voltava index.html — o player
# recebia HTML no lugar do MP4 e o "marcar como postado" nao chegava ao banco.
# Aqui os dois andam juntos: quem serve o site e o mesmo processo que serve a
# API, entao nao da mais para subir um sem o outro.
FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# As VITE_* sao lidas em tempo de BUILD (viram texto dentro do bundle).
# Chegam como build-arg porque no runtime ja e tarde.
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ARG VITE_DASHBOARD_PASSWORD
ARG VITE_TIKTOK_AUTH_BASE_URL
ARG VITE_TIKTOK_STANDARD_API_ENABLED
ARG VITE_TIKTOK_STANDARD_UPLOAD_DRAFT_ENABLED
ARG VITE_TIKTOK_STANDARD_DIRECT_POST_ENABLED
# Producao em Massa. VITE_MASS_API_URL vazia de proposito quando o painel e a
# API ficam no mesmo dominio (o server.mjs faz o proxy de /mass/): a pagina usa
# caminho relativo. Sem estas duas a aba nem entra no bundle.
ARG VITE_MASS_ENABLED
ARG VITE_MASS_API_URL
# Demais agentes locais, pela mesma regra: a URL vazia significa mesma origem.
ARG VITE_MULTICHANNEL_ENABLED
ARG VITE_VEXPUBLISH_API_URL
ARG VITE_IMPORT_ENABLED
ARG VITE_IMPORT_API_URL
ARG VITE_COMMERCE_ENABLED
ARG VITE_COMMERCE_API_URL

COPY . .
RUN npm run build

FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production PORT=80

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/server.mjs ./server.mjs
COPY --from=build /app/package.json ./package.json

EXPOSE 80
CMD ["node", "server.mjs"]
