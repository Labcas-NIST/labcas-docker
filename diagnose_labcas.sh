#!/bin/bash

# LabCAS Authentication Diagnostic Script
# =====================================
# This script diagnoses common authentication and networking issues in LabCAS deployment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Symbols
CHECK_MARK="✓"
CROSS_MARK="✗"
WARNING_MARK="⚠"

# Global variables
ISSUES_FOUND=0
WARNINGS_FOUND=0

# Helper functions
log_success() {
    echo -e "${GREEN}${CHECK_MARK}${NC} $1"
}

log_error() {
    echo -e "${RED}${CROSS_MARK}${NC} $1"
    ((ISSUES_FOUND++))
}

log_warning() {
    echo -e "${YELLOW}${WARNING_MARK}${NC} $1"
    ((WARNINGS_FOUND++))
}

log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_header() {
    echo ""
    echo -e "${BLUE}===========================================${NC}"
    echo -e "${BLUE} $1${NC}"
    echo -e "${BLUE}===========================================${NC}"
}

check_docker_compose() {
    log_header "Docker Compose and Container Status"
    
    # Check if docker-compose.yml exists
    if [[ -f "docker-compose.yml" ]]; then
        log_success "docker-compose.yml found"
    else
        log_error "docker-compose.yml not found in current directory"
        return 1
    fi
    
    # Check if containers are running
    local required_containers=("labcas-backend" "labcas-ui" "labcas-proxy" "ldap" "postgres")
    
    for container in "${required_containers[@]}"; do
        if docker ps --format "table {{.Names}}" | grep -q "^${container}$"; then
            log_success "Container ${container} is running"
        else
            log_error "Container ${container} is not running"
        fi
    done
}

check_docker_network() {
    log_header "Docker Network Configuration"
    
    # Get network name (usually labcas-docker_labcas-net)
    local network_name=$(docker network ls --format "{{.Name}}" | grep labcas-net | head -1)
    
    if [[ -n "$network_name" ]]; then
        log_success "Found Docker network: $network_name"
        
        # Check if all containers are on the same network
        local containers_on_network=$(docker network inspect "$network_name" --format '{{range .Containers}}{{.Name}} {{end}}')
        log_info "Containers on network: $containers_on_network"
        
        # Test internal hostname resolution
        if docker exec labcas-backend getent hosts ldap >/dev/null 2>&1; then
            log_success "Internal DNS resolution working (labcas-backend can resolve ldap)"
        else
            log_warning "Internal DNS resolution may have issues"
        fi
    else
        log_error "LabCAS Docker network not found"
    fi
}

check_nginx_proxy() {
    log_header "Nginx Proxy Configuration"
    
    # Check if nginx config exists and is valid
    if docker exec labcas-proxy nginx -t >/dev/null 2>&1; then
        log_success "Nginx configuration is valid"
    else
        log_error "Nginx configuration has syntax errors"
        docker exec labcas-proxy nginx -t 2>&1 | sed 's/^/    /'
    fi
    
    # Check if proxy routes are configured correctly
    local nginx_config=$(docker exec labcas-proxy cat /etc/nginx/sites-enabled/default 2>/dev/null || echo "")
    
    if echo "$nginx_config" | grep -q "location.*labcas-backend"; then
        log_success "Nginx has labcas-backend proxy configuration"
    else
        log_error "Nginx missing labcas-backend proxy configuration"
    fi
    
    if echo "$nginx_config" | grep -q "location.*labcas-ui"; then
        log_success "Nginx has labcas-ui proxy configuration"
    else
        log_error "Nginx missing labcas-ui proxy configuration"
    fi
    
    # Check upstream configurations
    if echo "$nginx_config" | grep -q "upstream labcas-backend"; then
        local backend_upstream=$(echo "$nginx_config" | grep -A 2 "upstream labcas-backend" | grep "server" | awk '{print $2}' | tr -d ';')
        log_success "Nginx upstream for labcas-backend: $backend_upstream"
    else
        log_error "Nginx missing upstream configuration for labcas-backend"
    fi
}

check_external_access() {
    log_header "External Access and Port Binding"
    
    # Check if ports are accessible from host
    local ports=("80:80" "443:443" "8082:8080" "8081:8081" "8444:8444")
    
    for port_mapping in "${ports[@]}"; do
        local host_port=$(echo "$port_mapping" | cut -d: -f1)
        local container_port=$(echo "$port_mapping" | cut -d: -f2)
        
        # Check if Docker is forwarding the port
        if docker ps --format "table {{.Names}}\t{{.Ports}}" | grep -q "0.0.0.0:${host_port}"; then
            log_success "Port $host_port is bound and listening"
        else
            log_info "Port $host_port not exposed (may be internal only)"
        fi
    done
    
    # Test HTTP to HTTPS redirect
    local http_response=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/ 2>/dev/null || echo "000")
    if [[ "$http_response" == "301" ]]; then
        log_success "HTTP to HTTPS redirect working (got 301)"
    else
        log_warning "HTTP to HTTPS redirect not working (got $http_response)"
    fi
}

check_labcas_backend_services() {
    log_header "LabCAS Backend Service Deployment"
    
    # Check if backend container is responsive
    local backend_health=$(curl -s -k -o /dev/null -w "%{http_code}" https://localhost:8444/ 2>/dev/null || echo "000")
    log_info "Direct backend access (port 8444) returns: $backend_health"
    
    # Check through proxy
    local proxy_backend_health=$(curl -s -k -o /dev/null -w "%{http_code}" https://localhost/labcas-backend/ 2>/dev/null || echo "000")
    log_info "Proxy backend access returns: $proxy_backend_health"
    
    # Check for specific authentication endpoint
    local auth_endpoint_response=$(curl -s -k -o /dev/null -w "%{http_code}" https://localhost/labcas-backend/labcas-backend-data-access-api/auth 2>/dev/null || echo "000")
    if [[ "$auth_endpoint_response" == "200" ]] || [[ "$auth_endpoint_response" == "405" ]]; then
        log_success "Authentication endpoint responds (HTTP $auth_endpoint_response)"
        
        # Test actual POST request as browser would do
        local post_response=$(curl -s -k -X POST -H "Content-Type: application/x-www-form-urlencoded" -o /dev/null -w "%{http_code}" https://localhost/labcas-backend/labcas-backend-data-access-api/auth 2>/dev/null || echo "000")
        if [[ "$post_response" == "200" ]] || [[ "$post_response" == "403" ]] || [[ "$post_response" == "401" ]]; then
            log_success "Authentication endpoint accepts POST requests (HTTP $post_response)"
            if [[ "$post_response" == "403" ]]; then
                log_info "HTTP 403 indicates auth endpoint is working but rejecting test credentials (expected)"
            fi
        else
            log_warning "Authentication endpoint POST returns unexpected: HTTP $post_response"
        fi
    elif [[ "$auth_endpoint_response" == "404" ]]; then
        log_error "Authentication endpoint not found (HTTP 404) - This is the main issue!"
        log_info "Expected endpoint: /labcas-backend/labcas-backend-data-access-api/auth"
    else
        log_warning "Authentication endpoint returns unexpected response: HTTP $auth_endpoint_response"
    fi
    
    # Check what services are actually running in backend
    log_info "Services running in labcas-backend container:"
    docker exec labcas-backend ps aux 2>/dev/null | grep -E "(java|tomcat)" | while read line; do
        echo "    $line"
    done
    
    # Check for deployed webapps
    if docker exec labcas-backend find /tmp/labcas -name "*.war" -o -name "webapps" 2>/dev/null | grep -q .; then
        log_info "Web applications found in labcas-backend:"
        docker exec labcas-backend find /tmp/labcas -name "*.war" -o -name "webapps" 2>/dev/null | sed 's/^/    /'
    else
        log_warning "No web applications found in expected locations"
    fi
}

check_ldap_connectivity() {
    log_header "LDAP Service Connectivity"
    
    # Check LDAP container health
    if docker exec ldap ps aux | grep -q slapd; then
        log_success "LDAP service (slapd) is running"
    else
        log_error "LDAP service (slapd) not running"
    fi
    
    # Test LDAP connectivity from backend
    if docker exec labcas-backend timeout 5 bash -c 'cat < /dev/null > /dev/tcp/ldap/1636' 2>/dev/null; then
        log_success "LDAP port 1636 is reachable from labcas-backend"
    else
        log_error "LDAP port 1636 is not reachable from labcas-backend"
    fi
    
    # Check LDAP configuration
    local ldap_config=$(docker exec labcas-backend cat /root/labcas.properties 2>/dev/null | grep ldap || echo "")
    if [[ -n "$ldap_config" ]]; then
        log_success "LDAP configuration found in labcas.properties"
        echo "$ldap_config" | sed 's/^/    /'
    else
        log_warning "No LDAP configuration found in labcas.properties"
    fi
}

check_ui_configuration() {
    log_header "LabCAS UI Configuration"
    
    # Check environment.cfg
    local env_config=$(docker exec labcas-ui cat /var/www/html/labcas-ui/assets/conf/environment.cfg 2>/dev/null || echo "{}")
    
    # Parse environment setting
    local environment=$(echo "$env_config" | grep -o '"environment"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
    if [[ -n "$environment" ]]; then
        log_success "UI environment configuration found: $environment"
        
        # Validate the environment path makes sense
        if [[ "$environment" == "/labcas-backend/" ]]; then
            log_success "Environment path is correctly configured for proxy"
        else
            log_warning "Environment path may not work with current proxy setup: $environment"
        fi
    else
        log_error "No environment configuration found in environment.cfg"
    fi
    
    # Check SSO configuration
    local sso_enabled=$(echo "$env_config" | grep -o '"sso_enabled"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
    if [[ "$sso_enabled" == "true" ]]; then
        log_info "SSO is enabled - login will redirect to SSO endpoint"
        local sso_url=$(echo "$env_config" | grep -o '"sso_login_url"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
        log_info "SSO login URL: $sso_url"
    else
        log_info "SSO is disabled - using direct authentication"
    fi
    
    # Test UI accessibility
    local ui_response=$(curl -s -k -o /dev/null -w "%{http_code}" https://localhost/labcas-ui/ 2>/dev/null || echo "000")
    if [[ "$ui_response" == "200" ]]; then
        log_success "LabCAS UI is accessible (HTTP 200)"
    else
        log_error "LabCAS UI not accessible (HTTP $ui_response)"
    fi
}

check_authentication_flow() {
    log_header "Authentication Flow Analysis"
    
    log_info "Expected authentication flow:"
    echo "    1. Browser loads https://localhost/labcas-ui/"
    echo "    2. JavaScript loads environment.cfg"
    echo "    3. User submits login form"
    echo "    4. AJAX POST to: \${environment}labcas-backend-data-access-api/auth"
    echo "    5. This becomes: https://localhost/labcas-backend/labcas-backend-data-access-api/auth"
    echo "    6. Nginx proxy forwards to: https://labcas-backend/labcas-backend-data-access-api/auth"
    echo "    7. Backend validates credentials against LDAP"
    echo ""
    
    # Test each step
    local step1=$(curl -s -k -o /dev/null -w "%{http_code}" https://localhost/labcas-ui/ 2>/dev/null || echo "000")
    if [[ "$step1" == "200" ]]; then
        log_success "Step 1: UI loads successfully"
    else
        log_error "Step 1: UI fails to load (HTTP $step1)"
    fi
    
    local step2=$(curl -s -k -o /dev/null -w "%{http_code}" https://localhost/labcas-ui/assets/conf/environment.cfg 2>/dev/null || echo "000")
    if [[ "$step2" == "200" ]]; then
        log_success "Step 2: environment.cfg loads successfully"
    else
        log_error "Step 2: environment.cfg fails to load (HTTP $step2)"
    fi
    
    local step5=$(curl -s -k -o /dev/null -w "%{http_code}" https://localhost/labcas-backend/labcas-backend-data-access-api/auth 2>/dev/null || echo "000")
    if [[ "$step5" == "405" ]] || [[ "$step5" == "200" ]]; then
        log_success "Step 5: Authentication endpoint exists (HTTP $step5)"
    elif [[ "$step5" == "404" ]]; then
        log_error "Step 5: Authentication endpoint missing (HTTP 404)"
        log_info "This is likely the root cause of login failures!"
    else
        log_warning "Step 5: Unexpected response from auth endpoint (HTTP $step5)"
    fi
}

generate_recommendations() {
    log_header "Recommendations and Next Steps"
    
    if [[ $ISSUES_FOUND -eq 0 ]]; then
        log_success "No critical issues found! Authentication should be working."
    else
        echo -e "${RED}Found $ISSUES_FOUND critical issue(s):${NC}"
        echo ""
        
        # Specific recommendations based on common issues
        if curl -s -k -o /dev/null -w "%{http_code}" https://localhost/labcas-backend/labcas-backend-data-access-api/auth 2>/dev/null | grep -q "404"; then
            echo "🔧 MAIN ISSUE: Authentication API not deployed"
            echo "   Solutions:"
            echo "   - Verify labcas-backend container has the authentication WAR deployed"
            echo "   - Check if the correct webapp is built and deployed to Tomcat"
            echo "   - Verify the authentication service endpoint path in backend code"
            echo ""
        fi
        
        if ! docker ps --format "table {{.Names}}" | grep -q "labcas-backend"; then
            echo "🔧 ISSUE: Backend container not running"
            echo "   Solutions:"
            echo "   - Run: docker-compose up -d labcas-backend"
            echo "   - Check docker-compose logs: docker-compose logs labcas-backend"
            echo ""
        fi
    fi
    
    if [[ $WARNINGS_FOUND -gt 0 ]]; then
        echo -e "${YELLOW}Found $WARNINGS_FOUND warning(s) that should be addressed.${NC}"
        echo ""
    fi
    
    echo "💡 Additional debugging steps:"
    echo "   - Check container logs: docker-compose logs"
    echo "   - Monitor network traffic: docker exec labcas-proxy tail -f /var/log/nginx/labcas-backend.error.log"
    echo "   - Test from inside containers: docker exec labcas-backend curl -k https://localhost:8444/"
    echo ""
    echo "📋 Configuration files to review:"
    echo "   - ./labcas-ui/environment.cfg"
    echo "   - ./labcas-backend/labcas.properties" 
    echo "   - ./labcas-proxy nginx configuration"
}

# Main execution
main() {
    echo -e "${BLUE}LabCAS Authentication Diagnostic Tool${NC}"
    echo -e "${BLUE}====================================${NC}"
    echo ""
    echo "Timestamp: $(date)"
    echo "Working directory: $(pwd)"
    echo ""
    
    check_docker_compose
    check_docker_network
    check_nginx_proxy
    check_external_access
    check_labcas_backend_services
    check_ldap_connectivity
    check_ui_configuration
    check_authentication_flow
    generate_recommendations
    
    echo ""
    echo -e "${BLUE}===========================================${NC}"
    if [[ $ISSUES_FOUND -eq 0 ]]; then
        echo -e "${GREEN}✓ Diagnosis complete: System appears healthy${NC}"
    else
        echo -e "${RED}✗ Diagnosis complete: $ISSUES_FOUND critical issues found${NC}"
    fi
    echo -e "${BLUE}===========================================${NC}"
    
    exit $ISSUES_FOUND
}

# Run the diagnostic
main "$@"