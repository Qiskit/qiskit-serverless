.DEFAULT_GOAL                := help
.DEFAULT_SHELL               := /bin/bash

HADOLINT_VERSION             ?= v2.12.0
CONFTEST_VERSION             ?= v0.43.1
TRIVY_VERSION                ?= 0.42.1
DTB_VERSION                  ?= 0.27.2

HADOLINT_DOCKER_IMAGE        := hadolint/hadolint:$(HADOLINT_VERSION)
OPENPOLICYAGENT_DOCKER_IMAGE := openpolicyagent/conftest:$(CONFTEST_VERSION)
TRIVY_DOCKER_IMAGE           := aquasec/trivy:$(TRIVY_VERSION)

VSCAN_EXIT_CODE              ?= 1
VSCAN_SECURITY_CHECKS        ?= vuln
VSCAN_SEVERITIES             ?= CRITICAL

ENVIRONMENT                  ?= staging
PROJECT_CHANGESET            := $(shell git rev-parse --verify HEAD 2>/dev/null)

DTB_LOGLEVEL                 ?= info
DTB_IMAGE                    := us.icr.io/quantum-serverless/dtb:$(DTB_VERSION)
DTB_SHELL                    := docker container run --rm --name=dtb \
                                    --env IBMCLOUD_API_KEY \
                                    --volume $(PWD):/workspace:ro \
                                    --entrypoint /bin/bash \
                                    --interactive --tty $(DTB_IMAGE)

define assert-set
	@$(if $($1),,$(error $(1) environment variable is not defined))
endef

define assert-command
	@$(if $(shell command -v $1 2>/dev/null),,$(error $(1) command not found))
endef

define assert-file
	@$(if $(wildcard $($1) 2>/dev/null),,$(error $($1) does not exist))
endef


.PHONY: help
help: ## Shows this pretty help screen
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make <target>\n\nTargets:\n"} /^[a-z0-9\/\_-]+:.*?##/ { printf " %-25s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

.PHONY: versions
versions:
	@echo "Hadolint version............... $(HADOLINT_VERSION)"
	@echo "ConfTest version............... $(CONFTEST_VERSION)"
	@echo "Trivy version.................. $(TRIVY_VERSION)"
	@echo "Deployment Tool Belt version... $(DTB_VERSION)"

.PHONY: docker/lint
docker/lint: ## Dockerfile linting
	@docker run --name hadolint --rm --interactive $(HADOLINT_DOCKER_IMAGE) < $(DOCKER_FILE)

.PHONY: docker/sast
docker/sast: ## Dockerfile SAST tests
	@docker run --name conftest --rm --volume $(PWD):/project $(OPENPOLICYAGENT_DOCKER_IMAGE) test --strict --parser dockerfile --policy ci/opa/dockerfile-security.rego $(DOCKER_FILE)

.PHONY: docker/login
docker/login: SHELL := /bin/bash
docker/login:
	$(call assert-set,IBMCLOUD_API_KEY)
	@echo $(IBMCLOUD_API_KEY)|docker login --username iamapikey --password-stdin $(DOCKER_REGISTRY) 2>/dev/null
	@echo $(IBMCLOUD_API_KEY)|docker login --username iamapikey --password-stdin us.icr.io 2>/dev/null

.PHONY: docker/build
docker/build:
	@docker build \
    --build-arg IMAGE_PY_VERSION=${PY_VERSION} \
	--build-arg TARGETARCH="amd64" \
    --tag $(DOCKER_IMAGE):$(IMAGE_TAG) \
    --file $(DOCKER_FILE) \
	.

.PHONY: docker/vscan
docker/vscan: docker/build ## Makes a vulnerability scan over the Docker image
	@docker run --rm --name=trivy \
		--env GITHUB_TOKEN \
    --volume /var/run/docker.sock:/var/run/docker.sock \
    -it $(TRIVY_DOCKER_IMAGE) image --no-progress \
    --exit-code $(VSCAN_EXIT_CODE) \
    --scanners $(VSCAN_SECURITY_CHECKS) \
    --severity $(VSCAN_SEVERITIES) \
    --ignore-unfixed $(DOCKER_IMAGE):$(IMAGE_TAG)

.PHONY: docker/release
docker/release: docker/login
docker/release: docker/build ## Builds and release over the Docker registry the image
	@echo "docker/release"
	@echo "Pushing: $(DOCKER_IMAGE):$(IMAGE_TAG)"
	@docker image push $(DOCKER_IMAGE):$(IMAGE_TAG)

.PHONY: docker/asoc-static-scan
docker/asoc-static-scan: 
	@docker run \
		-e KeyId=${ASOC_KEY_ID} \
		-e KeySecret=${ASOC_KEY_SECRET} \
		-e GitToken=${ASOC_GIT_TOKEN} \
		-v $(PWD)/ci/asoc/AsocStaticConfig:/asoc/AsocConfig \
		-v $(PWD):/asoc/StaticScan \
		-w /asoc \
		icr.io/quantum-public/asoc-automation:latest \
		/asoc/appscanBash.sh

.PHONY: docker/asoc-dynamic-scan
docker/asoc-dynamic-scan: 
	@docker run \
		-e KeyId=${ASOC_KEY_ID} \
		-e KeySecret=${ASOC_KEY_SECRET} \
		-e GitToken=${ASOC_GIT_TOKEN} \
		-v $(PWD)/ci/asoc/AsocDynamicConfig:/asoc/AsocConfig \
		-v $(PWD)/ci/asoc/DAST_CurlCommands.sh:/asoc/DAST_CurlCommands.sh \
		-w /asoc \
		icr.io/quantum-public/asoc-automation:latest \
		/asoc/appscanBash.sh

.PHONY: helm/check
helm/check: SHELL := $(DTB_SHELL)
helm/check: docker/login ## Helm check (template)
	$(call assert-set,IBMCLOUD_API_KEY)
	$(call assert-set,ENVIRONMENT)
	$(call assert-set,TARGET_SERVICE)
	@helm template \
		--debug \
		$(TARGET_SERVICE) \
		/workspace/charts/$(TARGET_SERVICE) \
		--values /workspace/ci/deployment/k8s/values/values-$(ENVIRONMENT).yaml

.PHONY: helm/deploy
helm/deploy: SHELL := $(DTB_SHELL)
helm/deploy: docker/login
	$(call assert-set,IBMCLOUD_API_KEY)
	$(call assert-set,ENVIRONMENT)
	$(call assert-set,TARGET_SERVICE)
#	@helm dependency update /workspace/charts/$(TARGET_SERVICE)
	@helm repo add bitnami https://charts.bitnami.com/bitnami
	@helm repo add kuberay https://ray-project.github.io/kuberay-helm
	@helm dep build /workspace/charts/$(TARGET_SERVICE)
#	@pydtb release \
#		--loglevel $(DTB_LOGLEVEL) \
#		--config /workspace/ci/deployment/k8s/conf/environments.yaml \
#		--environment $(ENVIRONMENT) \
#		--release $(TARGET_SERVICE) \
#		--chart /workspace/charts/$(TARGET_SERVICE) \
#		--values /workspace/ci/deployment/k8s/values/values-$(ENVIRONMENT).yaml
