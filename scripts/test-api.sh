#!/bin/bash
# Script to test the API endpoints

set -e

BASE_URL="http://localhost:8000"

echo "🧪 Testing recordya-chat API"
echo "======================="
echo ""

# Test 1: Health check
echo "1️⃣ Testing health endpoint..."
curl -s "$BASE_URL/health" | jq '.' || echo "❌ Health check failed"
echo ""

# Test 2: Register user
echo "2️⃣ Testing user registration..."
REGISTER_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "test123"
  }')
echo "$REGISTER_RESPONSE" | jq '.' || echo "User might already exist"
echo ""

# Test 3: Login
echo "3️⃣ Testing login..."
LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@test.com",
    "password": "admin123"
  }')
TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.access_token')
echo "Token: ${TOKEN:0:20}..."
echo ""

# Test 4: Get current user
echo "4️⃣ Testing /auth/me endpoint..."
curl -s "$BASE_URL/auth/me" \
  -H "Authorization: Bearer $TOKEN" | jq '.' || echo "❌ Auth failed"
echo ""

# Test 5: Get datasources
echo "5️⃣ Testing datasources endpoint..."
curl -s "$BASE_URL/api/datasources" \
  -H "Authorization: Bearer $TOKEN" | jq '.' || echo "❌ Datasources failed"
echo ""

# Test 6: Get usage
echo "6️⃣ Testing usage endpoint..."
curl -s "$BASE_URL/auth/usage" \
  -H "Authorization: Bearer $TOKEN" | jq '.' || echo "❌ Usage failed"
echo ""

echo "✅ API tests complete!"

