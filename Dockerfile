FROM ubuntu:18.04

RUN apt-get update &&\
    apt-get install -qy python2.7 python-pip python-dev libffi-dev libssl-dev
# RUN pip install pip-tools
ADD . /usr/src/app/
WORKDIR /usr/src/app
# RUN python -m piptools compile requirements.in
RUN pip install -r requirements.txt
RUN python setup.py install
EXPOSE 8000
