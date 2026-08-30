# syntax=docker/dockerfile:1.7

# Keep the official Gitpod runtime environment, but replace its older server
# payload with the newest upstream MIT release that Daedalus has verified.
FROM gitpod/openvscode-server@sha256:5e7b8750749f282940a799ed59ccd02fac698ef6744f9113ac01c0ef8e76485e

USER root

ADD --checksum=sha256:b433bf4f0227321a7014d8460d10a8f958adc0f45aa79bd889e84e65e8f88363 \
  https://github.com/gitpod-io/openvscode-server/releases/download/openvscode-server-v1.109.5/openvscode-server-v1.109.5-linux-x64.tar.gz \
  /tmp/openvscode-server.tar.gz

RUN rm -rf /home/.openvscode-server \
  && mkdir -p /home/.openvscode-server \
  && tar -xzf /tmp/openvscode-server.tar.gz \
      --strip-components=1 \
      -C /home/.openvscode-server \
  && rm /tmp/openvscode-server.tar.gz \
  && chown -R openvscode-server:openvscode-server /home/.openvscode-server

LABEL org.opencontainers.image.title="Daedalus OpenVSCode Server runtime" \
      org.opencontainers.image.version="1.109.5" \
      org.opencontainers.image.source="https://github.com/gitpod-io/openvscode-server"

USER openvscode-server
