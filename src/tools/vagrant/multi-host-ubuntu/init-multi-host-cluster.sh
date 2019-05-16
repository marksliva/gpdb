#!/bin/bash
set -ex

# For some reason, this env var does not get set correctly
# when running `docker exec -u gpadmin ...`
export USER=gpadmin

pushd /gpdb
    ssh-keyscan -t rsa sdw1 >> ~/.ssh/known_hosts
    ssh-keyscan -t rsa sdw2 >> ~/.ssh/known_hosts
    ssh-keyscan -t rsa sdw3 >> ~/.ssh/known_hosts
    ssh-keyscan -t rsa mdw >> ~/.ssh/known_hosts

    sshpass -p password scp ~/.ssh/id_rsa.pub gpadmin@sdw1:~/.ssh/authorized_keys
    sshpass -p password scp ~/.ssh/id_rsa.pub gpadmin@sdw2:~/.ssh/authorized_keys
    sshpass -p password scp ~/.ssh/id_rsa.pub gpadmin@sdw3:~/.ssh/authorized_keys
    cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys

    source /gpdb/src/tools/vagrant/multi-host-ubuntu/gpdb-env.sh

    gpssh-exkeys -f /gpdb/src/tools/vagrant/multi-host-ubuntu/all_hosts_list

    gpinitsystem -a -c /gpdb/src/tools/vagrant/multi-host-ubuntu/gpinitsystem_config

    createdb gptest
popd
