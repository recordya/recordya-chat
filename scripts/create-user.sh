#!/bin/bash
# Script to create a default user after the application starts
# In Keycloak mode the seed user comes from realm-export.json — no action needed.

set -e

echo "Waiting for backend to be ready..."
sleep 10

# Check auth mode from backend
AUTH_MODE=$(curl -sf http://localhost:8000/auth/config 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('auth_mode','local'))" 2>/dev/null || echo "local")

if [ "$AUTH_MODE" = "keycloak" ]; then
  echo "🔑 Keycloak mode detected — seed user (admin@test.com) is managed by Keycloak."
  echo "   Skipping local user creation."
  echo ""
  echo "Default credentials (Keycloak):"
  echo "  Email: admin@test.com"
  echo "  Password: admin123"
else
  echo "Creating default user (local mode)..."
  curl -X POST http://localhost:8000/auth/register \
    -H "Content-Type: application/json" \
    -d '{
      "email": "admin@test.com",
      "password": "admin123"
    }' || echo "User might already exist"

  echo ""
  echo "Default credentials (local):"
  echo "  Email: admin@test.com"
  echo "  Password: admin123"
fi

echo ""
echo "✅ Setup complete!"

