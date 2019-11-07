#!/bin/bash
set -x

service ssh start

locale-gen en_US.utf8
update-locale

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
