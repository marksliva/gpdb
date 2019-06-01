#!/bin/bash
set -x

/usr/sbin/sshd

service ssh start

date >> /home/gpadmin/docker_startup.txt

tail -f /dev/null
