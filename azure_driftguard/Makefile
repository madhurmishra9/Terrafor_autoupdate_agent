IMAGE ?= REGION-docker.pkg.dev/PROJECT/azure-driftguard/azure-driftguard:1.0.0
NS ?= azure-driftguard

.PHONY: test build push skills-configmap deploy logs

test:
	python tests/test_core.py

build:
	docker build -t $(IMAGE) .

push:
	docker push $(IMAGE)

# Generate the skills ConfigMap from the skills/ directory. Re-run after editing
# any SKILL.md to hot-update without rebuilding the image (ConfigMap delivery).
skills-configmap:
	kubectl create configmap azure-driftguard-skills \
		--from-file=skills/ \
		--namespace=$(NS) \
		--dry-run=client -o yaml | kubectl apply -f -

deploy:
	kubectl apply -f deploy/k8s/config-and-secrets.yaml
	$(MAKE) skills-configmap
	kubectl apply -f deploy/k8s/deployment.yaml
	kubectl apply -f deploy/k8s/cronjob.yaml

logs:
	kubectl logs -n $(NS) -l app=azure-driftguard -c azure-driftguard -f
