#!/bin/bash
set -ex

pushd /gpdb

docker network create --driver bridge gpdb_cluster_network

docker build --no-cache -t gpdb-multihost -f multihost.Dockerfile .

docker run --name=mdw --hostname=mdw -d -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost
docker run --name=sdw1 --hostname=sdw1 -d -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost
docker run --name=sdw2 --hostname=sdw2 -d -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost
docker run --name=sdw3 --hostname=sdw3 -d -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost

docker exec -u gpadmin mdw /gpdb/src/tools/vagrant/multi-host-ubuntu/init-multi-host-cluster.sh
