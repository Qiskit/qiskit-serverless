##############################################################################
# IKS on VPC Outputs
##############################################################################

output cluster_id {
    description = "ID of the IKS on VPC Cluster"
    value       = "${module.vpc_kubernetes_cluster.kubernetes_vpc_cluster_id}"
}

##############################################################################
