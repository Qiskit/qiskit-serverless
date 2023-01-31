##############################################################################
# Create a helm execution
##############################################################################

resource "helm_release" "quantum_serverless_release" {
  name       = "quantum-serverless-release"
  chart      = "../../helm/quantumserverless"

  values = [
    file("values.yaml")
  ]
}

##############################################################################
