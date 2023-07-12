##############################################################################
# IBM Cloud Provider
# > Remove for use in schematics
##############################################################################

terraform {
  required_providers {
    ibm = {
      source  = "IBM-Cloud/ibm"
      version = ">= 1.55.0"
    }
  }

  required_version = "~> 1.5"
}

provider "ibm" {
  ibmcloud_api_key = var.ibmcloud_api_key
  region           = var.ibmcloud_region
  ibmcloud_timeout = var.ibmcloud_timeout
}

##############################################################################

##############################################################################
# Cluster reference
##############################################################################

data "ibm_container_cluster_config" "quantum_serverless_cluster_config" {
  cluster_name_id = module.vpc_kubernetes_cluster.kubernetes_vpc_cluster_id
  resource_group_id = data.ibm_resource_group.ibmcloud_resource_group.id
}

##############################################################################

##############################################################################
# Resource Group
##############################################################################

data "ibm_resource_group" "ibmcloud_resource_group" {
  name = (var.ibmcloud_resource_group != null ? var.ibmcloud_resource_group : "default")
}

##############################################################################
