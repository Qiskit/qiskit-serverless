##############################################################################
# VPC - Subnet Resource
##############################################################################

module "vpc" {
  source  = "terraform-ibm-modules/vpc/ibm//modules/vpc"
  version = "1.1.2"

  create_vpc          = true
  vpc_name            = var.name
  resource_group_id   = data.ibm_resource_group.ibmcloud_resource_group.id
  vpc_tags            = var.tags
  locations           = var.locations
  subnet_name         = var.name
  number_of_addresses = var.number_of_addresses
  create_gateway      = true
  public_gateway_name = var.name
  gateway_tags        = var.tags
}

##############################################################################
