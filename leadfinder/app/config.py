"""Bootstrap configuration from environment (.env written by setup.sh).

Everything user-editable lives in the settings table (db.py) and is managed
from the dashboard — only secrets that must exist before first login and
deploy-level switches live here.
"""
import os

DATA_DIR = os.environ.get("DATA_DIR", "/data")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DASHBOARD_PASSWORD_HASH = os.environ.get("DASHBOARD_PASSWORD_HASH", "")
PUBLIC_IP = os.environ.get("PUBLIC_IP", "")
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
CERT_STAGING = os.environ.get("CERT_STAGING", "0") == "1"

# docker names pinned by docker-compose.yml (`name: vps-starter`)
NGINX_CONTAINER = "vps-starter-nginx"
LETSENCRYPT_VOLUME = "vps-starter_letsencrypt"
ACME_VOLUME = "vps-starter_acme-webroot"
NGINX_SITES_DIR = "/nginx-sites"
