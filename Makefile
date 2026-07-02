.PHONY: help up down restart logs logs-backend logs-frontend logs-db logs-keycloak \
       build clean setup create-user db-shell db-backup db-restore \
       dev-backend dev-frontend dev-test dev-test-backend dev-test-frontend \
       test test-backend test-frontend

# Plugin targets (auto-discovered from ../plugins/*/backend/evals/Makefile)
include $(wildcard ../plugins/*/backend/evals/Makefile)

# Resolve AUTH_MODE from .env (default: keycloak)
AUTH_MODE := $(shell grep -s '^AUTH_MODE=' .env | cut -d= -f2 || echo keycloak)
ifeq ($(AUTH_MODE),keycloak)
  COMPOSE := docker compose --profile sso
else
  COMPOSE := docker compose
endif

# Default target
help:
	@echo "recordya-chat — Commands"
	@echo ""
	@echo "Docker:"
	@echo "  make setup           - Initial setup (copy .env, start services, create user)"
	@echo "  make up              - Start all services"
	@echo "  make down            - Stop all services"
	@echo "  make restart         - Restart all services"
	@echo "  make logs            - Show logs (all services)"
	@echo "  make logs-backend    - Show backend logs"
	@echo "  make logs-frontend   - Show frontend logs"
	@echo "  make logs-keycloak   - Show Keycloak logs"
	@echo "  make build           - Rebuild all images"
	@echo "  make clean           - Stop and remove all containers, volumes, images"
	@echo "  make create-user     - Create default user (admin@test.com)"
	@echo ""
	@echo "Testing (Docker — requires make up):"
	@echo "  make test            - Run all tests (backend + frontend)"
	@echo "  make test-backend    - Run backend tests (pytest)"
	@echo "  make test-frontend   - Run frontend tests (vitest)"
	@echo ""
	@echo "Testing (local — requires .venv / npm install):"
	@echo "  make dev-test            - Run all tests locally"
	@echo "  make dev-test-backend    - Run backend tests locally"
	@echo "  make dev-test-frontend   - Run frontend tests locally"
	@echo ""
	@echo "Development (local):"
	@echo "  make dev-backend     - Start backend with hot reload"
	@echo "  make dev-frontend    - Start frontend dev server"
	@echo ""
	@echo "Database:"
	@echo "  make db-shell        - Connect to PostgreSQL"
	@echo "  make db-backup       - Backup database"
	@echo "  make db-restore FILE=backups/backup.sql"
	@echo ""

# Initial setup
setup:
	@echo "🚀 Setting up recordya-chat..."
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✅ Created .env file"; \
		echo "⚠️  Please edit .env and add your OPENAI_API_KEY"; \
		echo ""; \
		read -p "Press Enter after editing .env to continue..."; \
	fi
	@echo "🐳 Starting services (AUTH_MODE=$(AUTH_MODE))..."
	$(COMPOSE) up -d
	@echo "⏳ Waiting for services to be ready (30 seconds)..."
	@sleep 30
	@echo "👤 Creating default user..."
	@chmod +x scripts/create-user.sh
	@./scripts/create-user.sh
	@echo ""
	@echo "✅ Setup complete!"
	@echo "🌐 Frontend: http://localhost:8080"
	@echo "🔧 Backend: http://localhost:8000"
	@echo "🔑 Keycloak: http://localhost:8180"
	@echo "📧 Mailpit: http://localhost:8025"
	@echo "📚 API Docs: http://localhost:8000/docs"
	@echo ""
	@echo "⚠️  DEV ONLY — change or remove before any non-local deployment:"
	@echo "Login credentials (Keycloak SSO):"
	@echo "  Email: admin@test.com"
	@echo "  Password: admin123"
	@echo ""
	@echo "Keycloak Admin Console:"
	@echo "  URL: http://localhost:8180/admin"
	@echo "  User: admin"
	@echo "  Password: admin"

# Start services
up:
	$(COMPOSE) up -d
	@echo "✅ Services started (AUTH_MODE=$(AUTH_MODE))"
	@echo "🌐 Frontend: http://localhost:8080"
	@echo "🔧 Backend: http://localhost:8000"
	@echo "📧 Mailpit: http://localhost:8025"
ifeq ($(AUTH_MODE),keycloak)
	@echo "🔑 Keycloak: http://localhost:8180"
endif

# Stop services
down:
	$(COMPOSE) down
	@echo "✅ Services stopped"

# Restart services
restart:
	$(COMPOSE) restart
	@echo "✅ Services restarted"

# Show logs
logs:
	$(COMPOSE) logs -f

logs-backend:
	$(COMPOSE) logs -f backend

logs-frontend:
	$(COMPOSE) logs -f frontend

logs-db:
	$(COMPOSE) logs -f postgres

logs-keycloak:
	$(COMPOSE) logs -f keycloak

# Rebuild images
build:
	$(COMPOSE) build
	@echo "✅ Images rebuilt"

# Clean everything
clean:
	@echo "⚠️  This will remove all containers, volumes, and images!"
	@read -p "Are you sure? (y/N): " confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		$(COMPOSE) down -v; \
		docker system prune -af; \
		echo "✅ Cleanup complete"; \
	else \
		echo "❌ Cancelled"; \
	fi

# Create default user
create-user:
	@chmod +x scripts/create-user.sh
	@./scripts/create-user.sh

# Database commands
db-shell:
	$(COMPOSE) exec postgres psql -U recordyachat -d app_db

db-backup:
	@mkdir -p backups
	$(COMPOSE) exec postgres pg_dump -U recordyachat app_db > backups/backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "✅ Backup created in backups/"

db-restore:
	@if [ -z "$(FILE)" ]; then \
		echo "❌ Usage: make db-restore FILE=backups/backup.sql"; \
		exit 1; \
	fi
	$(COMPOSE) exec -T postgres psql -U recordyachat app_db < $(FILE)
	@echo "✅ Database restored from $(FILE)"

# Development commands
dev-backend:
	cd backend && .venv/bin/python -m uvicorn src.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test-backend:
	$(COMPOSE) run --rm backend sh -c 'python -m pytest tests/ $$(find /plugins/*/backend/tests -type d 2>/dev/null) -v'

test-frontend:
	$(COMPOSE) run --rm frontend npm run test

test: test-backend test-frontend

# Testing — local (requires .venv and npm install)
dev-test-backend:
	cd backend && .venv/bin/python -m pytest tests/ $$(find ../../plugins/*/backend/tests -type d 2>/dev/null) -v

dev-test-frontend:
	cd frontend && npm run test

dev-test: dev-test-backend dev-test-frontend

