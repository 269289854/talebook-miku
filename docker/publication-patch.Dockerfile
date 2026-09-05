# Build on a snapshot of the restored running container, preserving its patches.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY webserver/services/publication.py /var/www/talebook/webserver/services/publication.py
COPY webserver/handlers/publication.py /var/www/talebook/webserver/handlers/publication.py
COPY scripts/register_publication_route.py /tmp/register_publication_route.py
RUN /usr/bin/python3 /tmp/register_publication_route.py /var/www/talebook/webserver/handlers/__init__.py
COPY tests/test_publication.py /var/www/talebook/tests/test_publication.py
COPY scripts/check_publication_calibre.py scripts/check_publication_http.py /var/www/talebook/scripts/
COPY scripts/check_online_reading_regression.py /var/www/talebook/scripts/
