##############################################################################
# Create IKS on VPC Cluster
##############################################################################

module "vpc_kubernetes_cluster" {
  source                          = "terraform-ibm-modules/cluster/ibm//modules/vpc-kubernetes"
  version                         = "1.5.0"
  cluster_name                    = var.cluster_name
  vpc_id                          = ibm_is_vpc.vpc.id
  resource_group_id               = data.ibm_resource_group.resource_group.id
  disable_public_service_endpoint = var.disable_pse

  worker_pool_flavor = var.machine_type
  worker_zones = {
    var.zone_name = {
      subnet_id = ibm_is_subnet.subnet.id
    }
  }
}

##############################################################################
