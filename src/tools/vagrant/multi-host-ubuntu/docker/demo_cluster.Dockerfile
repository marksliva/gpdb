FROM ubuntu:18.04

COPY src/tools/vagrant/multi-host-ubuntu/docker/ubuntu18-requirements.sh /gpdb_src/ubuntu18-requirements.sh
RUN /gpdb_src/ubuntu18-requirements.sh

RUN mkdir /var/run/sshd
RUN echo 'root:nicepassword' | chpasswd
RUN sed -i 's/PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
# SSH login fix. Otherwise user is kicked off after login
RUN sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd
ENV NOTVISIBLE "in users profile"
RUN echo "export VISIBLE=now" >> /etc/profile
EXPOSE 22
CMD ["/usr/sbin/sshd", "-D"]

COPY . /gpdb_src

RUN gpdb_src/concourse/scripts/setup_gpadmin_user.bash
RUN usermod -aG sudo gpadmin

WORKDIR /gpdb_src

RUN bash -c "make distclean;\
CFLAGS='-O0 -g' ./configure --disable-gpcloud --disable-orca --disable-gpfdist --with-python --enable-debug --without-zstd"
RUN make install -j4 -s

RUN chown -R gpadmin:gpadmin /usr/local/gpdb
RUN chown -R gpadmin:gpadmin /gpdb_src
RUN chown -R gpadmin:gpadmin /etc/ssh/

RUN cat src/tools/vagrant/multi-host-ubuntu/docker/sysctl-conf >> /etc/sysctl.conf
RUN cat src/tools/vagrant/multi-host-ubuntu/docker/limits-conf >> /etc/security/limits.conf
RUN cat src/tools/vagrant/multi-host-ubuntu/docker/ld-so-conf >> /etc/ld.so.conf

RUN src/tools/vagrant/multi-host-ubuntu/docker/create-demo-cluster.sh
RUN src/tools/vagrant/multi-host-ubuntu/docker/install-gpupgrade.sh
