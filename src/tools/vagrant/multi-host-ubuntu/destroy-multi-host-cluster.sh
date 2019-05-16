#!/bin/bash

docker stop mdw sdw1 sdw2 sdw3
docker rm mdw sdw1 sdw2 sdw3

docker network rm gpdb_cluster_network
