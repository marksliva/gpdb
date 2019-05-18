# Multi-host gpdb
This tool is useful for creating a containerized gpdb cluster
on a VM, and it automates the entire process. It first provisions a VM using
Vagrant, and then creates a multi-host gpdb cluster on the VM using Docker.

It was initially designed for running and developing all behave tests
including ones tagged with `@concourse_cluster` on a developer machine.

## Requirements
* Install these tools before creating the vagrant vm:
    * Virtualbox
    * Vagrant
    * vagrant-disksize plugin: `vagrant plugin install vagrant-disksize`

## Create the VM and multi-host cluster
```
cd ~/workspace/gpdb-local-cluster/src/tools/vagrant/multi-host-ubuntu/
GPDB_REPO=~/workspace/gpdb-local-cluster vagrant up multi_host_ubuntu
```
- note: the shared directory GPDB_REPO will be mounted at /gpdb on the vm and all hosts in the cluster

## Connect to the VM
`vagrant ssh multi_host_ubuntu`

## SSH into mdw and run behave tests
```
docker exec -it mdw /bin/bash
su gpadmin
source /gpdb/src/tools/vagrant/multi-host-ubuntu/gpdb-env.sh
cd /gpdb/gpMgmt
make -f Makefile.behave behave flags='--tags gpmovemirrors --tags concourse_cluster'
```

## Destroy the VM
`vagrant destroy -f multi_host_ubuntu`
