apt-get update -y
apt-get install -y --no-install-recommends apt-utils openjdk-8-jdk software-properties-common
add-apt-repository -y ppa:ubuntu-toolchain-r/test
add-apt-repository -y ppa:longsleep/golang-backports
apt-get update -y
apt-get install -y --no-install-recommends gcc-6 g++-6 cmake
update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-6 60 --slave /usr/bin/g++ g++ /usr/bin/g++-6
update-alternatives --config gcc
gcc --version && g++ --version
apt-get install -y --no-install-recommends ant \
    bison \
    build-essential \
    ccache \
    curl \
    dirmngr \
    flex \
    gdb \
    git-core \
    golang-go \
    iputils-ping \
    iproute2 \
    jq \
    libapr1-dev \
    libbz2-dev \
    libcurl4-gnutls-dev \
    libevent-dev \
    libkrb5-dev \
    libpam-dev \
    libperl-dev \
    libreadline-dev \
    libssl-dev \
    $([ "$BASE_IMAGE" = ubuntu:18.04 ] && echo libxerces-c-dev) \
    libxml2-dev \
    libyaml-dev \
    libzstd1-dev \
    locales \
    maven \
    net-tools \
    ninja-build \
    openssh-server \
    pkg-config \
    python-dev \
    python-lockfile \
    python-pip \
    python-psutil \
    python-setuptools \
    less \
    rsync \
    ssh \
    sudo \
    time \
    unzip \
    vim \
    wget \
    zlib1g-dev
rm -rf /var/lib/apt/lists/*
