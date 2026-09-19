TOPO ?= topologies/global-pe-p-backbone.yaml
WIRING_IMAGE := lab-orchestrator-wiring

.PHONY: configs up wire down status full clean wiring-image

# Render EOS startup-configs from the topology YAML.
configs:
	python3 -m orchestrator.cli configs $(TOPO)

# Start containers (with --network=none — no interfaces until `wire`).
up: configs
	python3 -m orchestrator.cli up $(TOPO)

# Build the privileged helper image used only for wiring.
wiring-image:
	docker build -f scripts/Dockerfile.wiring -t $(WIRING_IMAGE) .

# Wire all veth pairs between running containers' namespaces.
# Runs inside the privileged helper — required on Docker Desktop
# (Mac/Windows) since the container namespaces live inside Docker's
# own VM, not a host you can `ip netns` into directly.
wire: wiring-image
	docker run --rm --privileged --pid=host \
		-v /var/run/docker.sock:/var/run/docker.sock \
		$(WIRING_IMAGE) wire $(TOPO)

# Tear everything down.
down:
	python3 -m orchestrator.cli down $(TOPO)

status:
	python3 -m orchestrator.cli status $(TOPO)

# The one command to reproduce the whole lab from nothing.
full: up wire
	@echo "Lab up. Run 'make status' to check, or 'docker exec -it dc1 Cli' to log in."

clean: down
	rm -rf configs/generated/*
