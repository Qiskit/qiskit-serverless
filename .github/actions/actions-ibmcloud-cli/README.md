# NOTE: THIS IS PRE RELEASE. DO NOT USE unless you know what you are doing.

# IBM Cloud CLI action

This action installs the IBM Cloud CLI and authenticates with IBM Cloud so you can run commands against it.

## Inputs

### `APIKEY`

**Required** Your API key to talk to the IBM Cloud

### `CLOUD_REGION`

**Required** The region you would like to interface with the IBM Cloud Default: `us-south`

## Example usage

```yaml
- name: Instal IBM Cloud CLI
  uses: actions/ibmcloud-action@v1
  with:
    APIKEY: ${{ secrets.IBM_CLOUD_API_KEY }}
    CLOUD_REGION: us-south
```

## License & Authors

If you would like to see the detailed LICENSE click [here](LICENSE).

- Author: JJ Asghar <awesome@ibm.com>

```text
Copyright:: 2020- IBM, Inc

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
