# Locker Phycer - Sovereign AI Security Infrastructure

Locker Phycer is a self-hosted, revenue-ready AI security control plane for regulated teams. It combines authentication, RBAC, AI request governance, security telemetry, marketplace execution packs, wallet billing, and audit evidence inside the customer's own cloud boundary.

## Features

### 🔒 Security & Authentication
- Zero-trust security architecture
- Multi-factor authentication (MFA)
- Role-based access control (RBAC)
- Advanced encryption and key management
- Real-time threat detection and response

### 🤖 AI & Machine Learning
- Intelligent threat analysis
- Predictive security analytics
- Automated incident response
- Behavioral pattern recognition
- Natural language processing for security logs

### 📊 Monitoring & Analytics
- Real-time system monitoring
- Performance metrics and dashboards
- Custom alerting and notifications
- Historical data analysis
- Compliance reporting

### 🔧 Infrastructure Management
- Container orchestration support
- Auto-scaling capabilities
- Load balancing and failover
- Backup and disaster recovery
- Multi-cloud deployment support

## Architecture

```
lockerphycer/
├── apps/
│   ├── api/                 # FastAPI backend services
│   └── web/                 # Frontend dashboard
├── core/
│   ├── config/              # Configuration management
│   ├── security/            # Security utilities
│   ├── database/            # Database connections
│   └── utils/               # Shared utilities
├── db/
│   ├── models/              # Database models
│   └── migrations/          # Database migrations
├── infra/
│   └── docker/              # Docker configurations
├── scripts/                 # Deployment and utility scripts
├── tests/                   # Test suites
├── docs/                    # Documentation
├── static/                  # Static assets
├── logs/                    # Application logs
├── data/                    # Application data
└── models/                  # AI/ML models
```

## Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- PostgreSQL 15+
- Redis 7+
- Node.js 18+ (for frontend)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/reprewindai-dev/lockerphycer.git
   cd lockerphycer
   ```

2. **Set up environment**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Start the application**
   ```bash
   uvicorn apps.api.main:app --reload
   ```

5. **Production with Docker**
   ```bash
   docker compose up --build
   ```

### Environment Variables

Key environment variables to configure:

```env
# Application
APP_NAME="Locker Phycer"
ENVIRONMENT=development
DEBUG=true
SECRET_KEY=your-secret-key-here

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/lockerphycer

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
AI_CITIZENSHIP_SECRET=your-ai-citizenship-secret
ENCRYPTION_KEY=your-encryption-key

# External Services
OPENAI_API_KEY=your-openai-key
HUGGINGFACE_API_KEY=your-huggingface-key
STRIPE_SECRET_KEY=your-stripe-key
```

## API Documentation

Once running, visit:
- **API Docs**: http://localhost:8010/docs
- **Admin Dashboard**: http://localhost:3000
- **Monitoring**: http://localhost:3001

## Development

### Running Tests
```bash
# Unit tests
pytest tests/

# Integration tests
pytest tests/integration/

# Coverage
pytest --cov=apps tests/
```

### Code Quality
```bash
# Linting
flake8 apps/
black apps/

# Type checking
mypy apps/
```

## Monetization

Locker Phycer ships with workspace tier state and wallet ledger support:

- Community: free, 5 seats, 500 AI requests, 7-day logs.
- Growth: $299/month, 25 seats, 5,000 AI requests, 30-day logs.
- Sovereign: $799/month, 100 seats, 10,000 AI requests, 90-day logs.
- Enterprise: custom air-gapped deployment, managed operations, and implementation fees.

## Deployment

### Docker Deployment
```bash
docker compose up --build
```

### Kubernetes
```bash
# Apply Kubernetes manifests
kubectl apply -f k8s/
```

## Monitoring

The application includes comprehensive monitoring:

- **Prometheus**: Metrics collection
- **Grafana**: Visualization and dashboards
- **Loki**: Log aggregation
- **AlertManager**: Alert management

## Security

### Authentication
- JWT-based authentication
- OAuth2 integration
- SAML support
- LDAP/Active Directory integration

### Encryption
- AES-256 encryption at rest
- TLS 1.3 in transit
- Key rotation support
- Hardware security module (HSM) support

### Compliance
- GDPR compliance
- SOC 2 Type II
- ISO 27001
- HIPAA (healthcare version)

## Support

- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/reprewindai-dev/lockerphycer/issues)
- **Discussions**: [GitHub Discussions](https://github.com/reprewindai-dev/lockerphycer/discussions)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

**Built with ❤️ by the Locker Phycer Team**
