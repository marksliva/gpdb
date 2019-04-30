# Useful commands

## create a user-defined network for the cluster
`docker network create --driver bridge gpdb_cluster_network`

## build a multinode container in the repo root
`docker build --no-cache -t gpdb-multihost -f multihost.Dockerfile .`

## run a multi node cluster from the greenplum repo
```
docker run --name=mdw --hostname=mdw -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost
docker run --name=sdw1 --hostname=sdw1 -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost
docker run --name=sdw2 --hostname=sdw2 -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost
docker run --name=sdw3 --hostname=sdw3 -v `pwd`:/gpdb --network=gpdb_cluster_network -p 22 -t gpdb-multihost
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

## build the container in the repo root
`docker build --no-cache -t gpdb1 -f demo_cluster.Dockerfile .`
- if you see an error during the `make install` step, run `git clean -dfx` and try again

## run on the user-defined network and expose the ssh and PGPORT ports
`docker run --rm --network=gpdb_cluster_network -p 22 -p 15432 -t gpdb1`

## if you want the container to be automatically deleted when you ctrl-c, run this instead:
`docker run -e MASTER_PORT=30000 -e STANDBY_PORT=31000 -e PORT_BASE=29000 --rm --network=gpdb_cluster_network -p 22 -p 30000 -t gpdb1`

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

# known issues
* there is contention for the port 15432 when starting multiple containers on the same host
    - a potential fix is to pass a PGPORT env var when doing a docker run command (`EXPOSE 15432` could then be removed from the Dockerfile)

# TODO
0. Create a script that sets up a multi host cluster that matches the concourse cluster provisioner cluster
1. Explore ways to quickly and reliably update running containers' code from the host while developing