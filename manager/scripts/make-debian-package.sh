#!/bin/bash

set -o errexit
set -o nounset

export DEBIAN_FRONTEND=noninteractive

# upgrade system to latest
apt-get update -qqq
apt-get upgrade -y -qqq

# configure repository with Knot Resolver dependencies
apt-get -y -qqq install apt-transport-https lsb-release ca-certificates wget curl gnupg2
sh -c 'echo "deb http://download.opensuse.org/repositories/home:/CZ-NIC:/knot-resolver-build/Debian_10/ /" > /etc/apt/sources.list.d/home:CZ-NIC:knot-resolver-build.list'
sh -c 'curl -fsSL https://download.opensuse.org/repositories/home:CZ-NIC:knot-resolver-build/Debian_10/Release.key | gpg --dearmor > /etc/apt/trusted.gpg.d/home_CZ-NIC_knot-resolver-build.gpg'
apt-get update -qqq

# apkg
apt-get install -y python3-pip
pip3 install apkg

# prepare the repo
git clone https://gitlab.nic.cz/knot/knot-resolver
cd knot-resolver
git config --global user.email "ci@knot-resolver"
git config --global user.name "GitLab CI"
git checkout manager-pkg
git rebase origin/manager-integration
git submodule update --init --recursive

# install meson, because its not installed for some reason
apt-get install -y meson

# build the package
apkg system-setup
apkg build -b
apkg srcpkg





