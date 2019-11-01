#!/bin/bash
set -x

su gpadmin -c '
    mkdir -p go/src/github.com/greenplum-db
    cd go/src/github.com/greenplum-db
    git clone https://github.com/greenplum-db/gpupgrade
    cd gpupgrade
    export PATH="${PATH}:${HOME}/go/bin"
    source /usr/local/gpdb/greenplum_path.sh
    source /gpdb_src/gpAux/gpdemo/gpdemo-env.sh

    make depend
    make
    make install
'
