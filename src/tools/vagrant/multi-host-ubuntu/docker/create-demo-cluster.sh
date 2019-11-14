#!/bin/bash
set -x

locale-gen en_US.utf8
update-locale

echo "service ssh start" >> $HOME/.bash_profile
service ssh start

su gpadmin -c '
    cd /gpdb_src

    hostname > gpAux/gpdemo/hostfile

    source /usr/local/gpdb/greenplum_path.sh
    make create-demo-cluster
    source gpAux/gpdemo/gpdemo-env.sh

    echo "host  all   all   0.0.0.0/0   trust" >> gpAux/gpdemo/datadirs/qddir/demoDataDir-1/pg_hba.conf
    gpstop -ar
'

#watch -n 5 'ps -ef wwf | grep postgres'
