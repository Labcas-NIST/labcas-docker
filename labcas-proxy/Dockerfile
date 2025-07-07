FROM labcas-ubuntubase

ARG installdir=/app/pdr/nerdm
# Define mountable directories.
VOLUME ["/etc/nginx/certs", "/var/log/nginx"]

RUN apt-get update && apt-get install -y iputils-ping net-tools bind9-host cron logrotate 
RUN chmod 4755 /bin/ping

ARG serverhost=localhost
ARG servercer=certs/local/localhost.cert.pem
ARG serverkey=certs/local/localhost.key.pem
ARG intermca=certs/local/no_intermediate.cer
ARG siteconf=default

RUN chmod a+x /var/log/nginx

COPY nginx-default.conf /tmp/default.conf.in
RUN sed -e '/server_name/ s/_;/'$serverhost';/' /tmp/default.conf.in \
        > /etc/nginx/sites-available/default
RUN (cd /etc/nginx/sites-enabled && ln -s ../sites-available/$siteconf $siteconf)

COPY $intermca  /etc/ssl/certs/intermediate-ca.cer
COPY $servercer /etc/ssl/certs/server.cer
COPY $serverkey /etc/ssl/private/server.key
RUN cat /etc/ssl/certs/intermediate-ca.cer >> /etc/ssl/certs/server.cer

COPY robots.txt /var/www/html


COPY entrypoint.sh $installdir/etc/entrypoint.sh
RUN chmod a+x $installdir/etc/entrypoint.sh

ENTRYPOINT ["/app/pdr/nerdm/etc/entrypoint.sh"]