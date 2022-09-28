##############################################################################
# Sensitive Account Variables
##############################################################################

variable ibmcloud_api_key {
  description = "The IBM Cloud platform API key needed to deploy IAM enabled resources"
}

##############################################################################


##############################################################################
# Account Variables
##############################################################################

variable ibm_region {
  description = "IBM Cloud region where all resources will be deployed"
}

variable resource_group {
  description = "Name of resource group to provision resources"
}

##############################################################################


##############################################################################
# VPC - Subnet - Gateway Variables
##############################################################################

variable vpc_name {
  description = "ID of VPC where cluster is to be created"
  default     = "quantum-serverless-vpc"
}

variable gateway_name {
  description = "name for the vpc public gateway"
  default     = "quantum-serverless-public-gateway"
}

variable subnet_name {
  description = "name for the vpc subnet"
  default     = "quantum-serverless-subnet"
}

variable zone_name {
  description = "name for the vpc subnet zone"
  default     = "us-south-1"
}

##############################################################################


##############################################################################
# Cluster Variables
##############################################################################

variable cluster_name {
  description = "name for the iks cluster"
  default     = "quantum-serverless-cluster"
}

variable machine_type {
  description = "Machine type for the IKS Cluster"
  default = "cx2.2x4"
}

variable worker_count {
  description = "Number of workers per zone"
  default     = 1
}

variable disable_pse {
  description = "Disable public service endpoint for cluster. True or false"
  default     = true
}

##############################################################################


##############################################################################
# Helm Variables
##############################################################################

variable helm_name {
  description = "Name of the helm that you will execute"
  default     = "quantum_serverless"
}

variable helm_path {
  description = "Path to the chart folder"
  default     = "../helm/quantumserverless"
}

variable values_file {
  description = "Path to the values file"
  default     = "terraform.yaml"
}

##############################################################################
