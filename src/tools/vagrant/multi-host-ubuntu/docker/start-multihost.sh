#!/bin/bash
set -x

/usr/sbin/sshd

service ssh start

date >> /home/gpadmin/docker_startup.txt

watch -n 5 'ps -ef wwf | grep postgres'
