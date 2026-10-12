ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY webserver/http_compress.py /var/www/talebook/webserver/http_compress.py
COPY scripts/register_json_gzip.py /tmp/register_json_gzip.py
RUN python3 /tmp/register_json_gzip.py /var/www/talebook \
    && python3 -m py_compile /var/www/talebook/webserver/main.py \
       /var/www/talebook/webserver/handlers/base.py /var/www/talebook/webserver/http_compress.py \
    && rm /tmp/register_json_gzip.py
