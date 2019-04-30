#!/bin/bash
set -x

/usr/sbin/sshd

/gpdb/concourse/scripts/setup_gpadmin_user.bash
usermod -aG sudo gpadmin

service ssh start

date >> /home/gpadmin/docker_startup.txt

watch -n 5 'ps -ef wwf | grep postgres'
