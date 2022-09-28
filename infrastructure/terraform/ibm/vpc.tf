##############################################################################
# VPC - Subnet Resource
##############################################################################

resource ibm_is_vpc vpc {
    name = "${var.vpc_name}"
    resource_group = "${data.ibm_resource_group.resource_group.id}"
}

resource ibm_is_public_gateway public_gateway {
  name           = "${var.gateway_name}"
  vpc            = "${ibm_is_vpc.vpc.id}"
  zone           = "${var.zone_name}"
  resource_group = "${data.ibm_resource_group.resource_group.id}"
}

resource ibm_is_subnet subnet {
  name            = "${var.subnet_name}"
  vpc             = "${ibm_is_vpc.vpc.id}"
  zone            = "${var.zone_name}"
  public_gateway  = "${ibm_is_public_gateway.public_gateway.id}"
  resource_group  = "${data.ibm_resource_group.resource_group.id}"

  total_ipv4_address_count = 64

  timeouts {
    create = "90m"
    delete = "30m"
  }
}

##############################################################################