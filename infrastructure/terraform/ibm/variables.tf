##############################################################################
# Sensitive Account Variables
##############################################################################

variable "ibmcloud_api_key" {
  description = "The IBM Cloud platform API key needed to deploy IAM enabled resources"
  type        = string
}

##############################################################################


##############################################################################
# Account Variables
##############################################################################

variable "ibm_region" {
  description = "IBM Cloud region where all resources will be deployed"
  type        = string
  default     = "us-south"
}

variable "resource_group" {
  description = "Name of resource group to provision resources"
  type        = string
  default     = "Default"
}

variable "ibmcloud_timeout" {
  description = "The general timeout to operate with the IBMCloud provider"
  type        = number
  default     = 60
}

##############################################################################


##############################################################################
# VPC - Subnet - Gateway Variables
##############################################################################

variable "vpc_name" {
  description = "ID of VPC where cluster is to be created"
  type        = string
  default     = "quantum-serverless-vpc"
}

variable "gateway_name" {
  description = "Name for the vpc public gateway"
  type        = string
  default     = "quantum-serverless-public-gateway"
}

variable "subnet_name" {
  description = "Name for the vpc subnet"
  type        = string
  default     = "quantum-serverless-subnet"
}

variable "zone_name" {
  description = "Name for the vpc subnet zone"
  type        = string
  default     = "us-south-1"
}

##############################################################################

##############################################################################
# Cluster Variables
##############################################################################

variable "cluster_name" {
  description = "name for the iks cluster"
  type        = string
  default     = "quantum-serverless-cluster"
}

variable "machine_type" {
  description = "Machine type for the IKS Cluster"
  type        = string
  default     = "cx2.2x4"
}

variable "worker_count" {
  description = "Number of workers per zone"
  type        = number
  default     = 1
}

variable "disable_pse" {
  description = "Disable public service endpoint for cluster. True or false"
  type        = bool
  default     = true
}

##############################################################################


##############################################################################
# Helm Variables
##############################################################################

variable "helm_name" {
  description = "Name of the helm that you will execute"
  type        = string
  default     = "quantum-serverless" #  This name should be DNS compliance
}

variable "helm_path" {
  description = "Path to the chart folder"
  type        = string
  default     = "../helm/quantumserverless"
}

variable "values_file" {
  description = "Path to the values file"
  type        = string
  default     = "terraform.yaml"
}

##############################################################################
