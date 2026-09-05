ARG BASE_IMAGE=talebook/talebook:v26.08.11@sha256:d6856c3880487174db9eeb3d0dbc2df9c96554cc709f6d08f67ca3163f1d2d9d
FROM ${BASE_IMAGE}

USER root
COPY apply_overlay.py /tmp/moke-online-reading-apply.py
RUN python3 /tmp/moke-online-reading-apply.py /var/www/talebook/webserver/handlers/book.py \
    /var/www/talebook/webserver/handlers/base.py \
    /etc/nginx/conf.d/talebook.conf \
    && rm -f /tmp/moke-online-reading-apply.py

LABEL org.opencontainers.image.title="TaleBook with Moke reading and library ordering"
LABEL org.opencontainers.image.description="Pinned v26.08.11 with authenticated inline reading and ordered library batches"
