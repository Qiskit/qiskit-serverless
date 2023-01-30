##############################################################################
# Create a helm execution
##############################################################################

resource helm_release quantum_serverless_helm {
  #name       = "${var.helm_name}"
  name       = "quantum-serverless-chart"
  #chart      = "${var.helm_path}"
  chart      = "../../helm/quantumserverless"

  #values = [
  #  "${file("${var.values_file}")}"
  #]
  values = [
    file("values.yaml")
  ]
}

##############################################################################
