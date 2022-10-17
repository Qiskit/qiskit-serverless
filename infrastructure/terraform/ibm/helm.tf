##############################################################################
# Create a helm execution
##############################################################################

# resource helm_release quantum_severless_helm {
#   depends_on = [
#     ibm_container_vpc_cluster.cluster
#   ]
#   name       = "${var.helm_name}"
#   chart      = "${var.helm_path}"

#   values = [
#     "${file("${var.values_file}")}"
#   ]
# }

##############################################################################
