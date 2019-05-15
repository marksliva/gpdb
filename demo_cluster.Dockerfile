FROM pivotaldata/ubuntu-gpdb-dev:16.04

RUN apt-get update && apt-get install -y openssh-server

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
CFLAGS='-O0 -g' ./configure --disable-orca --disable-gpfdist --with-python --prefix=/opt/gpdb --enable-debug --without-zstd"
RUN make install -j4 -s

RUN chown -R gpadmin /opt/gpdb
RUN chown -R gpadmin /gpdb_src
RUN chown -R gpadmin /etc/ssh/

RUN cat gpDocker/sysctl-conf >> /etc/sysctl.conf
RUN cat gpDocker/limits-conf >> /etc/security/limits.conf
RUN cat gpDocker/ld-so-conf >> /etc/ld.so.conf

ENTRYPOINT [ "/gpdb_src/gpDocker/create-demo-cluster.sh" ]
