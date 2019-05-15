#!/bin/bash
set -ex

pushd /gpdb
    ssh-keyscan -t rsa sdw1 >> ~/.ssh/known_hosts
    ssh-keyscan -t rsa sdw2 >> ~/.ssh/known_hosts
    ssh-keyscan -t rsa sdw3 >> ~/.ssh/known_hosts
    sshpass -p password scp ~/.ssh/id_rsa.pub gpadmin@sdw1:~/.ssh/authorized_keys
    sshpass -p password scp ~/.ssh/id_rsa.pub gpadmin@sdw2:~/.ssh/authorized_keys
    sshpass -p password scp ~/.ssh/id_rsa.pub gpadmin@sdw3:~/.ssh/authorized_keys

    source /opt/gpdb/greenplum_path.sh

    #gpssh-exkeys -h /gpdb/src/tools/vagrant/multi-host-ubuntu/segment_host_list

    mkdir -p /data/gpdata/master
    gpinitsystem -a -c /gpdb/src/tools/vagrant/multi-host-ubuntu/gpinitsystem_config
popd