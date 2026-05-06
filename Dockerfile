FROM python:3.12-alpine

WORKDIR /work

COPY indexer.py /usr/local/bin/coverage-pages-indexer
RUN chmod +x /usr/local/bin/coverage-pages-indexer

ENTRYPOINT ["/usr/local/bin/coverage-pages-indexer"]
