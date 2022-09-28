##############################################################################
# IBM Cloud Provider
# > Remove for use in schematics
##############################################################################

terraform {
  required_providers {
    ibm = {
      source = "IBM-Cloud/ibm"
      version = ">= 1.45.1"
    }
    helm = {
      source = "hashicorp/helm"
      version = ">= 2.6.0"
    }
  }
}

provider ibm {
  ibmcloud_api_key      = "${var.ibmcloud_api_key}"
  region                = "${var.ibm_region}"
  ibmcloud_timeout      = 60
}

provider helm {
  kubernetes {
    host     = "${ibm_container_vpc_cluster.cluster.public_service_endpoint_url}"
  }
}

##############################################################################


##############################################################################
# Resource Group
##############################################################################

data ibm_resource_group resource_group {
  name = "${var.resource_group}"
}

##############################################################################
