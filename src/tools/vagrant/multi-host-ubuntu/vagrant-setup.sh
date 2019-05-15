#!/bin/bash
set -ex

apt-get upgrade -y
apt-get -y install apt-transport-https dirmngr
KEY=8B48AD6246925553
# sometimes sks-keyservers doesn't respond, so use others as backup
for server in p80.pool.sks-keyservers.net pgp.mit.edu keyserver.ubuntu.com; do
  apt-key adv --no-tty --recv-key --keyserver "hkp://${server}:80" "$KEY" && break
done

curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
apt-key fingerprint 0EBFCD88 | grep '0EBF CD88' || exit 1

apt-get update

add-apt-repository \
   "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
   $(lsb_release -cs) \
   stable"

apt-get update

dependencies=(
apt-transport-https
build-essential
ca-certificates
containerd.io
curl
docker-ce
docker-ce-cli
git-core
gnupg-agent
pkg-config
python-pip
software-properties-common
vim
)

apt-get -y install "${dependencies[@]}"

service docker start
usermod -aG docker vagrant

chown -R vagrant:vagrant /usr/local

docker run hello-world

source /gpdb/src/tools/vagrant/multi-host-ubuntu/multi-host-cluster-create.sh