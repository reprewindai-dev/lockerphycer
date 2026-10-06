FROM debian:bookworm-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y postfix libsasl2-modules ca-certificates && rm -rf /var/lib/apt/lists/*
COPY main.cf /etc/postfix/main.cf
COPY sasl_passwd /etc/postfix/sasl_passwd
RUN postmap /etc/postfix/sasl_passwd
RUN chmod 600 /etc/postfix/sasl_passwd /etc/postfix/sasl_passwd.db
CMD ["postfix", "start-fg"]
