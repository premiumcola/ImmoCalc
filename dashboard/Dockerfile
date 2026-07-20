# nk-dashboard – statisches Frontend via nginx (Build-Context = Repo-Wurzel)
FROM nginx:1.27-alpine
ARG GIT_SHA=local
COPY public/ /usr/share/nginx/html/
# nginx-Image ersetzt ${API_UPSTREAM} beim Start (envsubst -> conf.d/default.conf)
COPY dashboard/nginx/default.conf.template /etc/nginx/templates/default.conf.template
# Ausserhalb von html/, weil public/ zur Laufzeit darueber gemountet wird.
RUN printf '%s\n' "$GIT_SHA" > /etc/nginx/build.txt
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost/healthz || exit 1
