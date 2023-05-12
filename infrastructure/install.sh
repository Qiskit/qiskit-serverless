#!/bin/bash

# Step 1: execute terraform
./terraform/ibm/install.sh


# Step 2: execute helm
./helm/quantumserverless/install.sh
