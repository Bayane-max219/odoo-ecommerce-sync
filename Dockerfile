FROM odoo:17.0

COPY . /mnt/extra-addons/odoo_ecommerce_sync/

USER root
RUN pip3 install --no-cache-dir requests urllib3
USER odoo
