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

variable "ibmcloud_region" {
  description = "IBM Cloud region where all resources will be deployed"
  type        = string
  default     = "us-south"
}

variable "ibmcloud_resource_group" {
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

variable "name" {
  description = "The prefix name for all the resources"
  type        = string
  default     = "quantum-serverless"
}

variable "tags" {
  description = "The list of tags"
  type        = list(string)
  default     = ["env:dev", "project:middleware"]
}

variable "locations" {
  description = "The locations for the subnets and nodes"
  type        = list(string)
  default     = ["us-south-1", "us-south-2"]
}

variable "number_of_addresses" {
  description = "The number of addresses by subnet"
  type        = number
  default     = 64
}

##############################################################################

##############################################################################
# Cluster Variables
##############################################################################

variable "machine_type" {
  description = "Machine type for the IKS Cluster"
  type        = string
  default     = "cx2.8x16"
}

variable "worker_nodes_per_zone" {
  description = "Number of workers per zone"
  type        = number
  default     = 2
}

variable "disable_pse" {
  description = "Disable public service endpoint for cluster. True or false"
  type        = bool
  default     = false
}

##############################################################################