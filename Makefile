
# --- Config: change these if your setup differs ---
CONTAINER_NAME := mariadb-project
IMAGE          := docker.io/library/mariadb:11.8
VOLUME         := mariadb-data
DB_NAME        := ragdb
DB_ROOT_PASS   := changeme
PORT           := 3306

.PHONY: help pull volume create start stop restart shell logs status rm clean recreate

help: ## Show available commands
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  make %-10s %s\n", $$1, $$2}'

pull: ## Pull the MariaDB image
	podman pull $(IMAGE)

volume: ## Create the persistent data volume (safe to run again)
	podman volume create $(VOLUME) || true

create: pull volume ## Create and start the container fresh (only if it doesn't exist)
	podman run -d \
		--name $(CONTAINER_NAME) \
		-e MARIADB_ROOT_PASSWORD=$(DB_ROOT_PASS) \
		-e MARIADB_DATABASE=$(DB_NAME) \
		-p $(PORT):3306 \
		-v $(VOLUME):/var/lib/mysql \
		$(IMAGE)

start: ## Start an already-created container
	podman start $(CONTAINER_NAME)

stop: ## Stop the running container
	podman stop $(CONTAINER_NAME)

restart: stop start ## Restart the container

shell: ## Open a mariadb SQL prompt inside the container
	podman exec -it $(CONTAINER_NAME) mariadb -u root -p$(DB_ROOT_PASS) $(DB_NAME)

logs: ## Tail the container logs
	podman logs -f $(CONTAINER_NAME)

status: ## Show whether the container is running
	podman ps -a --filter name=$(CONTAINER_NAME)

rm: stop ## Remove the container (keeps the volume/data)
	podman rm $(CONTAINER_NAME)

clean: rm ## Remove the container AND delete all data (irreversible)
	podman volume rm $(VOLUME)

recreate: clean create ## Wipe everything and start from a clean database
