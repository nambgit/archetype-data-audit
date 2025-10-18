# File: docs/solution_design.md

# File Archive Management System - Solution Design Document

## 1. Executive Summary

Hệ thống quản lý archive file tự động cho môi trường hybrid cloud, tích hợp M365 SharePoint, AWS S3 Glacier, và on-premise file servers.

## 2. System Architecture

### 2.1 High-Level Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                     Admin Interface Layer                   │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │ Web Browser │  │ REST API     │  │ Auth Service │        │
│  └─────────────┘  └──────────────┘  └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                        │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │ File Scanner│  │ Archive Svc  │  │ Restore Svc  │        │
│  └─────────────┘  └──────────────┘  └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      Data Layer                             │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │ RDS PostgreSQL │ S3 + Glacier │  │ SharePoint   │        │
│  └─────────────┘  └──────────────┘  └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Component Integration

#### A. Data Sources
- **File Server**: On-premise SMB/CIFS shares
- **SharePoint**: M365 document libraries via REST API
- **Active Directory**: Domain Users

#### B. Processing Components
- **Scanner Service**: Python-based file metadata collector
- **Archive Service**: AWS Lambda functions for automated archival
- **API Gateway**: Flask REST API for web interface

#### C. Storage Components
- **Hot Storage**: On-premise file servers, SharePoint
- **Cold Storage**: AWS S3 Glacier Instant Retrieval

#### D. Database Schema
- **FileMetadata**: Primary table for file information
- **AuditLog**: Tracks all system operations
- **UserSessions**: Manages admin authentication

### 2.3 Data Flow

#### First Scan Process:
1. Scanner connects to file server/SharePoint
2. Retrieves file metadata (name, path, size, owner, permissions, timestamps)
3. Calculates MD5 checksum for integrity verification
4. Stores metadata in RDS database
5. Logs scan completion in AuditLog

#### Archive Process:
1. Daily job identifies files not accessed in 180+ days
2. Uploads file to S3 with GLACIER storage class
3. Verifies upload via checksum comparison
4. Updates FileMetadata.FileStatus to 'Archived'
5. Deletes original file from source
6. Logs archive operation

#### Restore Process:
1. Admin selects archived file from web interface
2. System retrieves file from Glacier (if needed, initiates restore)
3. Downloads to temporary location
4. Verifies checksum integrity
5. Copies to original location with original permissions
6. Updates database status to 'Original'
7. Deletes from Glacier storage

## 3. Integration Points

### 3.1 SharePoint Integration
- **Protocol**: SharePoint REST API
- **Authentication**: OAuth 2.0
- **Operations**: List files, get metadata, delete items
- **Rate Limiting**: 600 requests per minute

### 3.2 AWS S3/Glacier Integration
- **SDK**: Boto3 (Python)
- **Storage Classes**: 
  - GLACIER_IR (cold data, > 180 days)
- **Lifecycle Policies**: Auto-transition after 180 days
- **Retrieval Time**: 
  - Expedited: 1-5 minutes
  - Standard: 3-5 hours

### 3.3 Active Directory Integration
- **Authentication**: Simple bind
- **Authorization**: Group membership check (IT Admins group)

### 3.4 Database Integration
- **Engine**: PostgreSQL on AWS RDS
- **SSL/TLS**: Required for all connections
- **Backup**: Automated daily snapshots, 7-day retention

## 4. Data Workflow

### 4.1 File Lifecycle
```
[New File Created]
        ↓
   [Original State]
   (File Server/SP)
        ↓
   [Scanned Daily]
   (Metadata collected)
        ↓
   [Access Check]
   (Last accessed < 180 days?)
        ↓
   [Yes] → [Archive Process]
           ↓
      [Archived State]
      (S3 Glacier)
           ↓
      [Admin Restore Request]
           ↓
      [Restored State]
      (Back to Original Location)
```

### 4.2 Metadata Management

**Captured Metadata:**
- File name, path, size
- Owner, permissions (POSIX/NTFS)
- Created, modified, accessed timestamps
- MD5 checksum
- Access count
- Current status (Original/Archived/Restored/Deleted)

**Metadata Updates:**
- Real-time: On file operations (archive, restore)
- Scheduled: Daily full scan at 2 AM
- Incremental: Continuous monitoring via file system events

## 5. Security Architecture

### 5.1 Authentication & Authorization
- **Admin Access**: authentication against Active Directory
- **API Security**: JWT tokens with HTTPS only
- **Service Accounts**: IAM roles for AWS services
- **Least Privilege**: Minimal permissions for each component

### 5.2 Data Protection
- **Encryption at Rest**: 
  - AWS S3: AES-256
  - RDS: Transparent Data Encryption (TDE)
- **Encryption in Transit**: 
  - TLS 1.2+ for all network communications
- **Checksum Verification**: MD5 hash for integrity

### 5.3 Audit & Compliance
- **Audit Log**: All operations logged with user, timestamp, details
- **Retention**: 90 days in database, 7 years in S3
- **Access Tracking**: Who accessed what, when, from where

## 6. Scalability & Performance

### 6.1 Performance Targets
- **Scan Performance**: 1000 files/minute
- **Archive Performance**: 100 MB/second upload
- **API Response Time**: < 500ms (95th percentile)
- **Database Query Time**: < 100ms (average)

### 6.2 Scalability Strategies
- **Horizontal Scaling**: Multiple scanner instances
- **Caching**: Redis for frequently accessed metadata
- **Async Processing**: Queue-based architecture for long-running tasks
- **Database Optimization**: Indexed queries, read replicas

## 7. Disaster Recovery

### 7.1 Backup Strategy
- **Database**: Daily automated snapshots, 7-day retention
- **S3 Data**: Versioning enabled, cross-region replication
- **Configuration**: Git repository with version control

### 7.2 Recovery Procedures
- **RTO (Recovery Time Objective)**: 4 hours
- **RPO (Recovery Point Objective)**: 24 hours
- **Failover**: Automated RDS failover to standby instance

## 8. Monitoring & Alerting

### 8.1 Metrics Tracked
- CPU, memory, disk utilization
- API request count, error rate
- Archive/restore success rate
- Database connection pool usage

### 8.2 Alerting Rules
- Failed archive operations > 5 in 1 hour
- API error rate > 5%
- Database connection pool exhaustion
- Disk usage > 80%

## 9. Deployment Strategy

### 9.1 Development Environment
- Local dev with Docker containers
- Mock S3 using LocalStack
- SQLite for local database

### 9.2 Staging Environment
- Mirrors production configuration
- Subset of production data
- Used for UAT and integration testing

### 9.3 Production Deployment
- Blue-green deployment for zero downtime
- Automated deployment via CI/CD pipeline
- Rollback capability within 5 minutes

## 10. Future Enhancements

### 10.1 Phase 2 Features
- Machine learning for intelligent archival prediction
- Multi-region support for global deployments
- Advanced search with Elasticsearch
- Mobile app for monitoring

### 10.2 Optimization Opportunities
- Delta sync for large files
- Deduplication to reduce storage costs
- Compression before archival
- Predictive restore based on access patterns