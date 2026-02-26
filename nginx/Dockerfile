FROM openresty/openresty:latest

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL -o /usr/local/openresty/lualib/resty/http.lua \
       https://raw.githubusercontent.com/ledgetech/lua-resty-http/master/lib/resty/http.lua \
    && curl -fsSL -o /usr/local/openresty/lualib/resty/http_headers.lua \
       https://raw.githubusercontent.com/ledgetech/lua-resty-http/master/lib/resty/http_headers.lua \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
