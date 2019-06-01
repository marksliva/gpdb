#!/bin/bash
set -ex

cd /gpdb
docker build --no-cache -t gpdb-multihost -f src/tools/vagrant/multi-host-ubuntu/docker/multihost.Dockerfile .

cd src/tools/vagrant/multi-host-ubuntu/docker
docker-compose up -d

docker exec -u gpadmin mdw src/tools/vagrant/multi-host-ubuntu/init-multi-host-cluster.sh
