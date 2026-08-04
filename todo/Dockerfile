ARG BUILD_FROM
FROM $BUILD_FROM

COPY app /app
RUN pip3 install --no-cache-dir /app

COPY run.sh /
RUN chmod a+x /run.sh

CMD ["/run.sh"]
