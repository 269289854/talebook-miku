# Build on the exact healthy production snapshot so existing overlays remain intact.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY webserver/device_api_keys.py /var/www/talebook/webserver/device_api_keys.py
COPY scripts/register_device_auth.py /tmp/register_device_auth.py
COPY scripts/check_device_auth_overlay.py /tmp/check_device_auth_overlay.py
RUN /usr/bin/python3 /tmp/register_device_auth.py /var/www/talebook \
    && /usr/bin/python3 -m py_compile \
        /var/www/talebook/webserver/device_api_keys.py \
        /var/www/talebook/webserver/models.py \
        /var/www/talebook/webserver/migrate_db.py \
        /var/www/talebook/webserver/handlers/user.py \
    && cd /var/www/talebook \
    && /usr/bin/python3 /tmp/check_device_auth_overlay.py /var/www/talebook \
    && rm -f /tmp/register_device_auth.py /tmp/check_device_auth_overlay.py
