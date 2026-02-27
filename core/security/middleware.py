"""
Security Middleware for FastAPI
"""

from fastapi import Request, HTTPException, status
from fastapi.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import time
import logging
from typing import Dict, Any, List
import json
from collections import defaultdict, deque
import asyncio
from datetime import datetime, timedelta

from core.config.settings import settings
from core.security.auth import is_safe_url, sanitize_input


class SecurityMiddleware(BaseHTTPMiddleware):
    """Security middleware for request filtering and protection"""
    
    def __init__(self, app):
        super().__init__(app)
        self.rate_limiter = RateLimiter()
        self.request_tracker = RequestTracker()
        self.security_headers = SecurityHeaders()
        
    async def dispatch(self, request: Request, call_next):
        """Process request through security checks"""
        
        # Get client IP
        client_ip = self._get_client_ip(request)
        
        # Rate limiting
        if not await self.rate_limiter.is_allowed(client_ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded"
            )
        
        # Request validation
        await self._validate_request(request, client_ip)
        
        # Track request
        self.request_tracker.add_request(client_ip, str(request.url.path))
        
        # Process request
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        
        # Add security headers
        response = self.security_headers.add_headers(response)
        
        # Log security events
        await self._log_security_event(request, response, process_time, client_ip)
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request"""
        # Check for forwarded IP
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        # Check for real IP
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        
        # Fall back to client IP
        return request.client.host if request.client else "unknown"
    
    async def _validate_request(self, request: Request, client_ip: str):
        """Validate request for security threats"""
        
        # Check URL safety
        if not is_safe_url(str(request.url)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsafe URL detected"
            )
        
        # Check for suspicious headers
        await self._check_suspicious_headers(request)
        
        # Check request size
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 10 * 1024 * 1024:  # 10MB limit
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Request too large"
            )
        
        # Check for blocked IPs (in production, this would check a database)
        if self._is_ip_blocked(client_ip):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    
    async def _check_suspicious_headers(self, request: Request):
        """Check for suspicious request headers"""
        suspicious_headers = [
            "X-Forwarded-Host",
            "X-Originating-IP",
            "X-Real-IP"
        ]
        
        for header in suspicious_headers:
            if header in request.headers:
                value = request.headers[header]
                if not self._is_valid_header_value(value):
                    logging.warning(f"Suspicious header detected: {header}={value}")
    
    def _is_valid_header_value(self, value: str) -> bool:
        """Validate header value for injection attempts"""
        dangerous_patterns = ["<script", "javascript:", "data:", "vbscript:"]
        return not any(pattern in value.lower() for pattern in dangerous_patterns)
    
    def _is_ip_blocked(self, ip: str) -> bool:
        """Check if IP is blocked (simplified implementation)"""
        # In production, this would check against a database or cache
        blocked_ips = []  # Would be populated from database
        return ip in blocked_ips
    
    async def _log_security_event(self, request: Request, response: Response, 
                                 process_time: float, client_ip: str):
        """Log security-related events"""
        
        # Log slow requests
        if process_time > 5.0:
            logging.warning(
                f"Slow request detected: {request.method} {request.url.path} "
                f"took {process_time:.2f}s from {client_ip}"
            )
        
        # Log error responses
        if response.status_code >= 400:
            logging.warning(
                f"Error response: {response.status_code} for {request.method} "
                f"{request.url.path} from {client_ip}"
            )
        
        # Log suspicious activity patterns
        if self.request_tracker.is_suspicious_activity(client_ip):
            logging.warning(
                f"Suspicious activity detected from {client_ip}: "
                f"multiple requests to sensitive endpoints"
            )


class RateLimiter:
    """Rate limiting implementation"""
    
    def __init__(self):
        self.requests: Dict[str, deque] = defaultdict(deque)
        self.lock = asyncio.Lock()
    
    async def is_allowed(self, client_ip: str) -> bool:
        """Check if client is allowed based on rate limits"""
        async with self.lock:
            now = time.time()
            
            # Clean old requests (older than 1 minute)
            cutoff = now - 60
            
            # Remove old requests from this IP
            while self.requests[client_ip] and self.requests[client_ip][0] < cutoff:
                self.requests[client_ip].popleft()
            
            # Check rate limit (100 requests per minute)
            if len(self.requests[client_ip]) >= 100:
                return False
            
            # Add current request
            self.requests[client_ip].append(now)
            return True


class RequestTracker:
    """Track requests for anomaly detection"""
    
    def __init__(self):
        self.requests: Dict[str, List[str]] = defaultdict(list)
        self.lock = asyncio.Lock()
    
    def add_request(self, client_ip: str, path: str):
        """Add request to tracker"""
        asyncio.create_task(self._add_request_async(client_ip, path))
    
    async def _add_request_async(self, client_ip: str, path: str):
        """Async add request"""
        async with self.lock:
            self.requests[client_ip].append(path)
            
            # Keep only last 100 requests per IP
            if len(self.requests[client_ip]) > 100:
                self.requests[client_ip] = self.requests[client_ip][-100:]
    
    def is_suspicious_activity(self, client_ip: str) -> bool:
        """Check for suspicious activity patterns"""
        if client_ip not in self.requests:
            return False
        
        recent_requests = self.requests[client_ip][-10:]  # Last 10 requests
        
        # Check for multiple requests to sensitive endpoints
        sensitive_endpoints = ["/admin", "/api/v1/users", "/api/v1/security"]
        sensitive_count = sum(1 for path in recent_requests 
                            if any(endpoint in path for endpoint in sensitive_endpoints))
        
        return sensitive_count >= 5


class SecurityHeaders:
    """Security headers middleware"""
    
    def add_headers(self, response: Response) -> Response:
        """Add security headers to response"""
        
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # XSS Protection
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Strict Transport Security (HTTPS only)
        if settings.IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Content Security Policy
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers["Content-Security-Policy"] = csp
        
        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions Policy
        permissions_policy = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=()"
        )
        response.headers["Permissions-Policy"] = permissions_policy
        
        return response


class IntrusionDetectionSystem:
    """Basic intrusion detection system"""
    
    def __init__(self):
        self.signatures = self._load_signatures()
        self.alerts = []
    
    def _load_signatures(self) -> List[Dict[str, Any]]:
        """Load intrusion detection signatures"""
        return [
            {
                "name": "SQL Injection",
                "patterns": ["union select", "drop table", "insert into", "delete from"],
                "severity": "high"
            },
            {
                "name": "XSS Attempt",
                "patterns": ["<script", "javascript:", "onerror=", "onload="],
                "severity": "medium"
            },
            {
                "name": "Path Traversal",
                "patterns": ["../", "..\\", "%2e%2e%2f"],
                "severity": "high"
            },
            {
                "name": "Command Injection",
                "patterns": ["; rm", "; cat", "| nc", "&& wget"],
                "severity": "critical"
            }
        ]
    
    def analyze_request(self, request: Request) -> Dict[str, Any]:
        """Analyze request for intrusion attempts"""
        threats = []
        
        # Analyze URL
        url_threats = self._analyze_string(str(request.url.path))
        threats.extend(url_threats)
        
        # Analyze query parameters
        for param, value in request.query_params.items():
            param_threats = self._analyze_string(f"{param}={value}")
            threats.extend(param_threats)
        
        # Analyze headers
        for header, value in request.headers.items():
            header_threats = self._analyze_string(f"{header}={value}")
            threats.extend(header_threats)
        
        return {
            "threats": threats,
            "risk_score": self._calculate_risk_score(threats),
            "recommendations": self._get_recommendations(threats)
        }
    
    def _analyze_string(self, input_string: str) -> List[Dict[str, Any]]:
        """Analyze string for threat patterns"""
        threats = []
        input_lower = input_string.lower()
        
        for signature in self.signatures:
            for pattern in signature["patterns"]:
                if pattern in input_lower:
                    threats.append({
                        "type": signature["name"],
                        "pattern": pattern,
                        "severity": signature["severity"],
                        "context": input_string
                    })
        
        return threats
    
    def _calculate_risk_score(self, threats: List[Dict[str, Any]]) -> int:
        """Calculate risk score based on threats"""
        severity_scores = {"low": 1, "medium": 5, "high": 10, "critical": 20}
        return sum(severity_scores.get(threat["severity"], 1) for threat in threats)
    
    def _get_recommendations(self, threats: List[Dict[str, Any]]) -> List[str]:
        """Get security recommendations based on threats"""
        recommendations = []
        
        if any(threat["type"] == "SQL Injection" for threat in threats):
            recommendations.append("Implement input validation and parameterized queries")
        
        if any(threat["type"] == "XSS Attempt" for threat in threats):
            recommendations.append("Sanitize all user input and implement CSP headers")
        
        if any(threat["type"] == "Path Traversal" for threat in threats):
            recommendations.append("Validate file paths and implement chroot jails")
        
        if any(threat["type"] == "Command Injection" for threat in threats):
            recommendations.append("Avoid shell commands and use safe APIs")
        
        return recommendations


# Global IDS instance
ids = IntrusionDetectionSystem()
