#!/bin/bash
set -x

service ssh start

watch -n 5 'ps -ef wwf | grep postgres'
