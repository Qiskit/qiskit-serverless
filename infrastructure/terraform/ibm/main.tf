##############################################################################
# IBM Cloud Provider
# > Remove for use in schematics
##############################################################################

terraform {
  required_providers {
    ibm = {
      source  = "IBM-Cloud/ibm"
      version = ">= 1.50.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.8.0"
    }
  }

  required_version = "~> 1.2"
}

provider "ibm" {
  ibmcloud_api_key = var.ibmcloud_api_key
  region           = var.ibmcloud_region
  ibmcloud_timeout = var.ibmcloud_timeout
}

provider "helm" {
  kubernetes {
    host = ibm_container_vpc_cluster.cluster.public_service_endpoint_url
  }
}

##############################################################################


##############################################################################
# Resource Group
##############################################################################

data "ibm_resource_group" "ibmcloud_resource_group" {
  name = (var.ibmcloud_resource_group != null ? var.ibmcloud_resource_group : "default")
}

##############################################################################
