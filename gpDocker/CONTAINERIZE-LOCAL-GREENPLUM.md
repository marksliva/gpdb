# Useful commands

## create a user-defined network for the cluster
`docker network create --driver bridge gpdb_cluster_network`

# Multi host vagrant vm:
## create the VM (automatically starts up the cluster)
```
cd src/tools/vagrant/multi-host-ubuntu/
GPDB_REPO=~/workspace/gpdb-local-cluster vagrant up multi_host_ubuntu
```
- note: the shared directory GPDB_REPO will be mounted at /gpdb on the vm and all hosts in the cluster
## connect to the VM
`vagrant ssh multi_host_ubuntu`

## ssh into mdw
`docker exec -it mdw /bin/bash`

## destroy the vm
`vagrant destroy -f multi_host_ubuntu`

# Multi host docker:

## build a multi host container in the repo root
`docker build --no-cache -t gpdb-multihost -f multihost.Dockerfile .`

## run a multi host cluster from the greenplum repo
```
docker run --name=mdw --hostname=mdw -d -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost
docker run --name=sdw1 --hostname=sdw1 -d -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost
docker run --name=sdw2 --hostname=sdw2 -d -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost
docker run --name=sdw3 --hostname=sdw3 -d -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost
```
## set up 1-N ssh from mdw
```
docker exec -it mdw /bin/bash
su gpadmin

ssh-keyscan -t rsa sdw1 >> ~/.ssh/known_hosts
ssh-keyscan -t rsa sdw2 >> ~/.ssh/known_hosts
ssh-keyscan -t rsa sdw3 >> ~/.ssh/known_hosts
sshpass -p password scp ~/.ssh/id_rsa.pub gpadmin@sdw1:~/.ssh/authorized_keys
sshpass -p password scp ~/.ssh/id_rsa.pub gpadmin@sdw2:~/.ssh/authorized_keys
sshpass -p password scp ~/.ssh/id_rsa.pub gpadmin@sdw3:~/.ssh/authorized_keys
```
## set up the cluster
```
gpssh-exkeys -f hosts-file

on each host:
mkdir -p /data/gpdata
chown -R gpadmin:gpadmin /data
on mdw:
mkdir /data/gpdata/master
all hosts:
mkdir /data/gpdata/primary
mkdir /data/gpdata/mirror

gpinitsystem -c gpinitsystem_config -h hosts-file
```
# Single host:

## build the container in the repo root
`docker build --no-cache -t gpdb -f demo_cluster.Dockerfile .`
- if you see an error during the `make install` step, run `git clean -dfx` and try again

## run on the user-defined network and expose the ssh and PGPORT ports
`docker run -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -p 30000 -t gpdb`

## You can also override the ports
`docker run -v `pwd`:/gpdb -e MASTER_PORT=30000 -e STANDBY_PORT=31000 -e PORT_BASE=29000 --network=gpdb_cluster_network -p 22 -p 30000 -t gpdb`

# Other commands:

## list the running images to get the postgres and ssh ports
`docker ps`

## connect to gpdb from the host
`psql -U gpadmin -p 12345 postgres`

## ssh into a container from the host
`ssh -p 12345 gpadmin@localhost`

## start a root shell on the container
`docker exec -it container_id /bin/bash`

## ssh from one container to another
`ssh gpadmin@172.18.0.2`
