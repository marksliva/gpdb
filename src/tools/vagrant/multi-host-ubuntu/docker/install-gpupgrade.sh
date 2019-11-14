#!/bin/bash
set -x

cd /tmp

PROTOC_ZIP=protoc-3.9.1-linux-x86_64.zip
wget https://github.com/protocolbuffers/protobuf/releases/download/v3.9.1/$PROTOC_ZIP
unzip -o $PROTOC_ZIP -d /usr/local bin/protoc
unzip -o $PROTOC_ZIP -d /usr/local 'include/*'

git clone https://github.com/bats-core/bats-core.git
cd bats-core
./install.sh /usr/local

su gpadmin -c '
    cd $HOME
    mkdir -p go/bin
    curl https://raw.githubusercontent.com/golang/dep/master/install.sh | sh
    rm -f $PROTOC_ZIP
    mkdir -p go/src/github.com/greenplum-db
    cd go/src/github.com/greenplum-db
    git clone https://github.com/greenplum-db/gpupgrade
    cd gpupgrade
    export PATH="${HOME}/go/bin:${PATH}"
    source /usr/local/gpdb/greenplum_path.sh
    source /gpdb_src/gpAux/gpdemo/gpdemo-env.sh
    make depend-dev
    make depend
    make
    make install
'

# todo: get go/bin to always be in $PATH
#su gpadmin -c "echo 'export PATH=$HOME/go/bin:$PATH' >> $HOME/.bash_profile"
