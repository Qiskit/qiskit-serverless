##############################################################################
# Create a helm execution
##############################################################################

resource "helm_release" "quantum_serverless_chart" {
  name       = "quantum-serverless-chart"
  chart      = "../../helm/quantumserverless"

  values = [
    file("values.yaml")
  ]
}

##############################################################################
