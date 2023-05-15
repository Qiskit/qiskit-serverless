#!/bin/sh -l

curl -fsSL https://clis.cloud.ibm.com/install/linux | sh
ibmcloud --version
ibmcloud config --check-version=false
ibmcloud plugin install -f kubernetes-service
ibmcloud plugin install -f container-registry
ibmcloud login --apikey "$1" -r "$2" -g default
ibmcloud cr region-set "$2"
ibmcloud cr login
