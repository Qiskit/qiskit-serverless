##############################################################################
# IBM Cloud Provider
# > Remove for use in schematics
##############################################################################

terraform {
  required_providers {
    ibm = {
      source  = "IBM-Cloud/ibm"
      version = ">= 1.46.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.6.0"
    }
  }

  required_version = "~> 1.2"
}

provider "ibm" {
  ibmcloud_api_key = var.ibmcloud_api_key
  region           = var.ibm_region
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

data "ibm_resource_group" "resource_group" {
  name = var.resource_group
}

##############################################################################
