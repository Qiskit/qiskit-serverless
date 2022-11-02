# Quantum serverless deployment for IBM Cloud

## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | ~> 1.2 |
| <a name="requirement_helm"></a> [helm](#requirement\_helm) | >= 2.6.0 |
| <a name="requirement_ibm"></a> [ibm](#requirement\_ibm) | >= 1.46.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_ibm"></a> [ibm](#provider\_ibm) | 1.46.0 |

## Modules

| Name | Source | Version |
|------|--------|---------|
| <a name="module_vpc"></a> [vpc](#module\_vpc) | terraform-ibm-modules/vpc/ibm//modules/vpc | 1.1.1 |
| <a name="module_vpc_kubernetes_cluster"></a> [vpc\_kubernetes\_cluster](#module\_vpc\_kubernetes\_cluster) | terraform-ibm-modules/cluster/ibm//modules/vpc-kubernetes | 1.5.0 |

## Resources

| Name | Type |
|------|------|
| [ibm_resource_group.ibmcloud_resource_group](https://registry.terraform.io/providers/IBM-Cloud/ibm/latest/docs/data-sources/resource_group) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_disable_pse"></a> [disable\_pse](#input\_disable\_pse) | Disable public service endpoint for cluster. True or false | `bool` | `false` | no |
| <a name="input_ibmcloud_api_key"></a> [ibmcloud\_api\_key](#input\_ibmcloud\_api\_key) | The IBM Cloud platform API key needed to deploy IAM enabled resources | `string` | n/a | yes |
| <a name="input_ibmcloud_region"></a> [ibmcloud\_region](#input\_ibmcloud\_region) | IBM Cloud region where all resources will be deployed | `string` | `"us-south"` | no |
| <a name="input_ibmcloud_resource_group"></a> [ibmcloud\_resource\_group](#input\_ibmcloud\_resource\_group) | Name of resource group to provision resources | `string` | `"Default"` | no |
| <a name="input_ibmcloud_timeout"></a> [ibmcloud\_timeout](#input\_ibmcloud\_timeout) | The general timeout to operate with the IBMCloud provider | `number` | `60` | no |
| <a name="input_locations"></a> [locations](#input\_locations) | The locations for the subnets and nodes | `list(string)` | <pre>[<br>  "us-south-1",<br>  "us-south-2"<br>]</pre> | no |
| <a name="input_machine_type"></a> [machine\_type](#input\_machine\_type) | Machine type for the IKS Cluster | `string` | `"cx2.2x4"` | no |
| <a name="input_name"></a> [name](#input\_name) | The prefix name for all the resources | `string` | `"qserverless"` | no |
| <a name="input_number_of_addresses"></a> [number\_of\_addresses](#input\_number\_of\_addresses) | The number of addresses by subnet | `number` | `64` | no |
| <a name="input_tags"></a> [tags](#input\_tags) | The list of tags | `list(string)` | <pre>[<br>  "env:dev",<br>  "project:qserverless"<br>]</pre> | no |
| <a name="input_worker_nodes_per_zone"></a> [worker\_nodes\_per\_zone](#input\_worker\_nodes\_per\_zone) | Number of workers per zone | `number` | `1` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_cluster_id"></a> [cluster\_id](#output\_cluster\_id) | ID of the IKS on VPC Cluster |
