ARG BUILD_FROM=ghcr.io/hassio-addons/base:13.1.1
FROM ${BUILD_FROM}

ENV LANG C.UTF-8

COPY rootfs /
RUN chmod +x /usr/bin/maestrogateway.sh

RUN apk add --no-cache \
    coreutils=9.1-r0 \
    wget=1.21.4-r0 \
    py3-pip

COPY ./requirements.txt /requirements.txt

RUN pip3 install -r /requirements.txt && rm requirements.txt

ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="Dominik Haas <rage@cloudwar.de>" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.vendor="Home Assistant Community Add-ons" \
    org.opencontainers.image.authors="Dominik Haas <rage@cloudwar.de>" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.url="https://addons.community" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/README.md" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}

CMD [ "/usr/bin/maestrogateway.sh" ]
