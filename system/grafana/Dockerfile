# Grafana on Cloud Run with the Google Cloud Monitoring datasource (covers Managed Prometheus too).
FROM grafana/grafana-oss:11.4.0
COPY provisioning /etc/grafana/provisioning
ENV GF_SERVER_HTTP_PORT=8080 GF_AUTH_ANONYMOUS_ENABLED=false GF_SECURITY_ADMIN_USER=admin
