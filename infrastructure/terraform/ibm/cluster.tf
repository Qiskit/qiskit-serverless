##############################################################################
# Create IKS on VPC Cluster
##############################################################################

module "vpc_kubernetes_cluster" {
  source  = "terraform-ibm-modules/cluster/ibm//modules/vpc-kubernetes"
  version = "1.5.0"

  cluster_name                    = var.name
  vpc_id                          = module.vpc.vpc_id[0]
  resource_group_id               = data.ibm_resource_group.ibmcloud_resource_group.id
  disable_public_service_endpoint = var.disable_pse

  worker_pool_flavor    = var.machine_type
  worker_nodes_per_zone = var.worker_nodes_per_zone

  // TODO: This should be more flexible
  worker_zones = {
    us-south-1 = {
      subnet_id = module.vpc.subnet_ids[0]
    },
    us-south-2 = {
      subnet_id = module.vpc.subnet_ids[1]
    }
  }
}

##############################################################################
